"""
Service for grouping tweets into events and generating summaries.
"""
import re
import time
import logging
from typing import List, Dict, Tuple
from datetime import date
from collections import Counter
from django.db import transaction
from django.db.utils import OperationalError
from django.utils import timezone
# Lazy imports for sklearn - only import when actually needed
# import numpy as np
from .models import TwitterList, ListTweet, Event, EventTweet
from .summarization_service import SummarizationService

logger = logging.getLogger(__name__)

# Constants
DEFAULT_MIN_TWEETS_PER_EVENT = 3
DEFAULT_SIMILARITY_THRESHOLD = 0.3
DEFAULT_TOP_KEYWORDS = 10
MIN_WORD_LENGTH = 3
MAX_FEATURES_SMALL = 50
MAX_FEATURES_LARGE = 100
LARGE_DATASET_THRESHOLD = 200


class EventService:
    """
    Service for identifying and grouping tweets into events.
    
    This service uses text similarity analysis to group related tweets
    into events, then generates summaries for each event.
    """
    
    def __init__(
        self, 
        min_tweets_per_event: int = DEFAULT_MIN_TWEETS_PER_EVENT, 
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    ):
        """
        Initialize the event service.
        
        Args:
            min_tweets_per_event: Minimum number of tweets required to form an event
            similarity_threshold: Minimum similarity score (0-1) for tweets to be grouped
        """
        self.min_tweets_per_event = min_tweets_per_event
        self.similarity_threshold = similarity_threshold
        self.summarization_service = SummarizationService()
    
    def _preprocess_text(self, text: str) -> str:
        """Clean and preprocess tweet text for similarity comparison."""
        if not text:
            return ""
        
        # Remove URLs
        text = re.sub(r'http\S+|www\.\S+', '', text)
        
        # Remove mentions but keep the username part (sometimes useful)
        text = re.sub(r'@\w+', '', text)
        
        # Remove hashtags but keep the word part
        text = re.sub(r'#(\w+)', r'\1', text)
        
        # Remove extra whitespace
        text = ' '.join(text.split())
        
        # Convert to lowercase
        text = text.lower()
        
        return text.strip()
    
    def _extract_keywords(self, texts: List[str], top_n: int = DEFAULT_TOP_KEYWORDS) -> List[str]:
        """Extract top keywords from a list of texts."""
        if not texts:
            return []
        
        # Combine all texts
        combined_text = ' '.join(texts)
        
        # Simple keyword extraction: count word frequencies
        words = re.findall(rf'\b\w{{{MIN_WORD_LENGTH},}}\b', combined_text.lower())
        
        # Remove common stop words
        stop_words = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'her', 'was',
            'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'its', 'may',
            'new', 'now', 'old', 'see', 'two', 'who', 'way', 'use', 'her', 'she', 'him',
            'this', 'that', 'with', 'from', 'have', 'been', 'will', 'what', 'when', 'where',
            'which', 'there', 'their', 'they', 'them', 'these', 'those', 'than', 'then',
            'about', 'after', 'before', 'during', 'while', 'until', 'since', 'because',
            'though', 'although', 'however', 'therefore', 'moreover', 'furthermore',
            'would', 'could', 'should', 'might', 'must', 'shall', 'may', 'can', 'cannot'
        }
        
        words = [w for w in words if w not in stop_words]
        
        # Count frequencies
        word_counts = Counter(words)
        
        # Get top N keywords
        top_keywords = [word for word, count in word_counts.most_common(top_n)]
        
        return top_keywords
    
    def _calculate_similarity_matrix(self, texts: List[str]):
        """Calculate pairwise similarity matrix for texts using TF-IDF."""
        # Lazy import sklearn
        try:
            import numpy as np
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            logger.warning("sklearn or numpy not installed. Using simple similarity calculation.")
            # Return simple similarity matrix without numpy
            # Create identity-like matrix (1.0 on diagonal, 0.3 elsewhere)
            matrix = []
            for i in range(len(texts)):
                row = []
                for j in range(len(texts)):
                    if i == j:
                        row.append(1.0)
                    else:
                        row.append(0.3)
                matrix.append(row)
            return matrix
        
        import numpy as np  # Now safe to import since we're past the try/except
        
        if len(texts) < 2:
            return np.array([[1.0]])
        
        # Preprocess texts
        processed_texts = [self._preprocess_text(text) for text in texts]
        
        # Filter out empty texts
        non_empty = [(i, text) for i, text in enumerate(processed_texts) if text]
        if len(non_empty) < 2:
            # If too few non-empty texts, return identity matrix
            return np.eye(len(texts))
        
        indices, valid_texts = zip(*non_empty)
        
        # Create TF-IDF vectors
        vectorizer = TfidfVectorizer(
            max_features=100,
            ngram_range=(1, 2),  # Unigrams and bigrams
            min_df=1,  # Minimum document frequency
            stop_words='english'
        )
        
        try:
            tfidf_matrix = vectorizer.fit_transform(valid_texts)
            similarity_matrix = cosine_similarity(tfidf_matrix)
            
            # Create full similarity matrix (including empty texts)
            full_matrix = np.eye(len(texts))
            for i, idx_i in enumerate(indices):
                for j, idx_j in enumerate(indices):
                    full_matrix[idx_i, idx_j] = similarity_matrix[i, j]
            
            return full_matrix
        except Exception as e:
            print(f"Error calculating similarity matrix: {e}")
            # Return identity matrix as fallback
            return np.eye(len(texts))
    
    def _cluster_tweets(self, texts: List[str]) -> List[int]:
        """
        Cluster tweets into events using DBSCAN.
        
        Returns:
            List of cluster labels (-1 for noise/outliers)
        """
        # Lazy import sklearn
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.cluster import DBSCAN
        except ImportError:
            print("Warning: sklearn not installed. Using simple clustering (all tweets in one cluster).")
            # Fallback: put all tweets in one cluster
            return [0] * len(texts) if texts else []
        
        if len(texts) < 2:
            return [0] if texts else []
        
        # Use DBSCAN for clustering
        # eps: maximum distance between samples in the same cluster
        # min_samples: minimum number of samples in a cluster
        eps = 1 - self.similarity_threshold  # Convert similarity threshold to distance
        min_samples = max(2, self.min_tweets_per_event)
        
        # Preprocess texts
        processed_texts = [self._preprocess_text(text) for text in texts]
        non_empty_indices = [i for i, text in enumerate(processed_texts) if text]
        
        if len(non_empty_indices) < 2:
            return [0] * len(texts)
        
        valid_texts = [processed_texts[i] for i in non_empty_indices]
        
        try:
            # For large datasets, use fewer features to speed up processing
            max_features = MAX_FEATURES_SMALL if len(texts) > LARGE_DATASET_THRESHOLD else MAX_FEATURES_LARGE
            
            vectorizer = TfidfVectorizer(
                max_features=max_features,
                ngram_range=(1, 2),
                min_df=1,
                stop_words='english'
            )
            tfidf_matrix = vectorizer.fit_transform(valid_texts)
            
            # Use DBSCAN with cosine distance
            clustering = DBSCAN(
                eps=eps,
                min_samples=min_samples,
                metric='cosine',
                n_jobs=-1  # Use all available CPU cores
            )
            cluster_labels = clustering.fit_predict(tfidf_matrix)
            
            # Map back to full list (assign empty texts to -1)
            full_labels = [-1] * len(texts)
            for idx, label in zip(non_empty_indices, cluster_labels):
                full_labels[idx] = int(label)
            
            return full_labels
        except Exception as e:
            logger.error(f"Error in clustering: {e}", exc_info=True)
            # Fallback: assign all to same cluster
            return [0] * len(texts)
    
    def group_tweets_into_events(
        self,
        twitter_list: TwitterList,
        event_date: date,
        min_tweets: int = None
    ) -> List[Event]:
        """
        Group tweets from a list on a specific date into events.
        
        Args:
            twitter_list: The Twitter list to process
            event_date: The date to process tweets for
            min_tweets: Override minimum tweets per event (defaults to self.min_tweets_per_event)
        
        Returns:
            List of created/updated Event objects
        """
        if min_tweets is None:
            min_tweets = self.min_tweets_per_event
        
        # Get all list tweets for this date
        list_tweets = ListTweet.objects.filter(
            twitter_list=twitter_list,
            seen_date=event_date
        ).select_related('tweet').order_by('-tweet__created_at')
        
        tweet_count = list_tweets.count()
        print(f"[EVENT SERVICE] Processing {tweet_count} tweets for event generation")
        
        if tweet_count < min_tweets:
            print(f"Not enough tweets ({tweet_count}) to form events (minimum: {min_tweets})")
            return []
        
        # Extract tweet texts
        print(f"[EVENT SERVICE] Extracting tweet texts...")
        tweets_data = []
        for list_tweet in list_tweets:
            tweets_data.append({
                'list_tweet': list_tweet,
                'text': list_tweet.tweet.text_content or '',
                'tweet_id': list_tweet.tweet.tweet_id,
            })
        
        if not tweets_data:
            return []
        
        # Cluster tweets - this can be slow for large datasets
        print(f"[EVENT SERVICE] Clustering {len(tweets_data)} tweets (this may take a while for large datasets)...")
        texts = [item['text'] for item in tweets_data]
        cluster_labels = self._cluster_tweets(texts)
        print(f"[EVENT SERVICE] Clustering complete. Found {len(set(cluster_labels))} clusters")
        
        # Group tweets by cluster
        clusters: Dict[int, List[Dict]] = {}
        for item, label in zip(tweets_data, cluster_labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(item)
        
        # Filter out noise clusters (label -1) and small clusters
        valid_clusters = {
            label: items for label, items in clusters.items()
            if label != -1 and len(items) >= min_tweets
        }
        
        if not valid_clusters:
            print(f"No valid event clusters found (minimum {min_tweets} tweets per event)")
            return []
        
        # Create or update events
        # Use individual transactions per event to avoid long-held locks
        print(f"[EVENT SERVICE] Creating/updating events for {len(valid_clusters)} valid clusters...")
        events = []
        for cluster_idx, (cluster_id, cluster_tweets) in enumerate(valid_clusters.items(), 1):
            print(f"[EVENT SERVICE] Processing cluster {cluster_idx}/{len(valid_clusters)} ({len(cluster_tweets)} tweets)...")
            # Extract keywords from cluster (before transaction)
            cluster_texts = [item['text'] for item in cluster_tweets]
            keywords = self._extract_keywords(cluster_texts, top_n=10)
            
            # Generate summary using AI (before transaction)
            # This can be slow, especially for large clusters
            print(f"[EVENT SERVICE] Generating AI summary for cluster {cluster_idx} ({len(cluster_tweets)} tweets)...")
            try:
                headline, summary = self.summarization_service.generate_event_summary(
                    cluster_texts,
                    keywords
                )
                print(f"[EVENT SERVICE] Summary generated for cluster {cluster_idx}")
            except Exception as e:
                print(f"Error generating summary for cluster {cluster_id}: {e}")
                # Fallback: use first tweet as headline and simple summary
                headline = cluster_tweets[0]['text'][:200] + "..."
                summary = f"Event with {len(cluster_tweets)} related tweets about: {', '.join(keywords[:5])}"
            
            # Determine the actual event_date from tweet content
            # event_date should be when the event happened (from tweet.created_at),
            # not when it was processed (processing_date/seen_date)
            # Use the date of the earliest tweet in the cluster as the event_date
            tweet_dates = [
                item['list_tweet'].tweet.created_at.date() 
                for item in cluster_tweets 
                if item['list_tweet'].tweet.created_at
            ]
            if tweet_dates:
                actual_event_date = min(tweet_dates)  # Use earliest tweet date
            else:
                actual_event_date = event_date  # Fallback to processing date if no tweet dates
            
            # Create or update event in its own transaction to minimize lock time
            # Add retry logic for SQLite lock errors
            max_retries = 3
            retry_delay = 0.1  # Start with 100ms delay
            
            for attempt in range(max_retries):
                try:
                    with transaction.atomic():
                        # Check if an event already exists with the same set of tweets
                        # This prevents creating duplicate events when regenerating
                        list_tweet_ids = {item['list_tweet'].id for item in cluster_tweets}
                        
                        existing_event = None
                        # Check existing events for this list (search by actual event_date, not processing date)
                        for candidate_event in Event.objects.filter(
                            twitter_list=twitter_list,
                            event_date=actual_event_date
                        ).prefetch_related('event_tweets__list_tweet'):
                            # Get tweet IDs for this event
                            candidate_tweet_ids = {
                                et.list_tweet.id 
                                for et in candidate_event.event_tweets.all()
                            }
                            # If the sets match, this is the same cluster
                            if candidate_tweet_ids == list_tweet_ids:
                                existing_event = candidate_event
                                break
                        
                        if existing_event:
                            # Update existing event (regenerating with new summary)
                            existing_event.headline = headline
                            existing_event.summary = summary
                            existing_event.tweet_count = len(cluster_tweets)
                            existing_event.keywords = keywords
                            existing_event.updated_at = timezone.now()
                            existing_event.save()
                            event = existing_event
                            created = False
                        else:
                            # Create new event for this cluster
                            # Use actual_event_date (from tweet content) not event_date (processing date)
                            event = Event.objects.create(
                                twitter_list=twitter_list,
                                event_date=actual_event_date,  # When event happened, not when processed
                                headline=headline,
                                summary=summary,
                                tweet_count=len(cluster_tweets),
                                keywords=keywords,
                            )
                            created = True
                        
                        # Associate tweets with event
                        for item in cluster_tweets:
                            list_tweet = item['list_tweet']
                            
                            # Calculate relevance score (simple: based on position in cluster)
                            # Could be improved with actual similarity scores
                            relevance_score = 1.0
                            
                            EventTweet.objects.get_or_create(
                                event=event,
                                list_tweet=list_tweet,
                                defaults={'relevance_score': relevance_score}
                            )
                        
                        events.append(event)
                        print(f"[EVENT SERVICE] Cluster {cluster_idx} processed successfully")
                        break  # Success, exit retry loop
                        
                except OperationalError as e:
                    if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                        # Retry with exponential backoff
                        wait_time = retry_delay * (2 ** attempt)
                        print(f"Database locked, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                        time.sleep(wait_time)
                        continue
                    else:
                        # Max retries reached or different error
                        print(f"Failed to create event for cluster {cluster_id} after {max_retries} attempts: {e}")
                        import traceback
                        print(traceback.format_exc())
                        break  # Exit retry loop
                except Exception as e:
                    # Log error but continue with other events
                    print(f"Error creating event for cluster {cluster_id}: {e}")
                    import traceback
                    print(traceback.format_exc())
                    break  # Exit retry loop on non-lock errors
            
            # Small delay between clusters to allow SQLite to release locks
            # This is especially important if multiple clusters update the same event
            if cluster_id != list(valid_clusters.keys())[-1]:  # Don't delay after last cluster
                time.sleep(0.05)  # 50ms delay between clusters
        
        print(f"Created/updated {len(events)} events from {len(tweets_data)} tweets")
        return events
