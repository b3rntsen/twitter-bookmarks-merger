"""
Service for categorizing tweets using AI (Anthropic Claude or OpenAI).
"""
import json
import logging
from typing import List, Dict, Optional
from decouple import config

logger = logging.getLogger(__name__)

# Constants
DEFAULT_MAX_TWEET_LENGTH = 500
DEFAULT_MAX_TWEET_LENGTH_SUMMARY = 300
DEFAULT_MAX_TOKENS_CATEGORIZE = 4000
DEFAULT_MAX_TOKENS_SUMMARY = 1000


class TweetCategorizationService:
    """Service to categorize tweets using AI (Anthropic Claude or OpenAI)."""
    
    def __init__(self, provider: str = 'anthropic'):
        """
        Initialize the categorization service.
        
        Args:
            provider: 'anthropic' or 'openai'
        """
        self.provider = provider
        self.client = None
        self.model = None
        self._initialized = False
    
    def _initialize(self):
        """Lazy initialization of the AI client."""
        if self._initialized:
            return
        
        if self.provider == 'anthropic':
            try:
                from anthropic import Anthropic
                api_key = config('ANTHROPIC_API_KEY', default='')
                if not api_key:
                    raise ValueError(
                        "ANTHROPIC_API_KEY not found in environment variables. "
                        "Please set ANTHROPIC_API_KEY in your .env file or environment."
                    )
                self.client = Anthropic(api_key=api_key)
                self.model = config('ANTHROPIC_MODEL', default='claude-sonnet-4-20250514')
            except ImportError:
                raise ValueError("Anthropic package not installed. Run: pip install anthropic")
            except Exception as e:
                raise ValueError(f"Failed to initialize Anthropic client: {e}")
        
        elif self.provider == 'openai':
            try:
                from openai import OpenAI
                api_key = config('OPENAI_API_KEY', default='')
                if not api_key:
                    raise ValueError(
                        "OPENAI_API_KEY not found in environment variables. "
                        "Please set OPENAI_API_KEY in your .env file or environment."
                    )
                self.client = OpenAI(api_key=api_key)
                self.model = config('OPENAI_MODEL', default='gpt-4o')
            except ImportError:
                raise ValueError("OpenAI package not installed. Run: pip install openai")
            except Exception as e:
                raise ValueError(f"Failed to initialize OpenAI client: {e}")
        
        else:
            raise ValueError(f"Unknown provider: {self.provider}. Must be 'anthropic' or 'openai'")
        
        self._initialized = True
    
    def categorize_tweets(self, tweets: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Categorize tweets into meaningful categories.
        
        Args:
            tweets: List of tweet dictionaries with text_content, author_username, etc.
        
        Returns:
            Dictionary mapping category names to lists of tweets in that category
        """
        if not tweets:
            return {}
        
        # Initialize client if not already done
        self._initialize()
        
        # Prepare tweet data
        tweet_texts = []
        for i, tweet in enumerate(tweets):
            author = tweet.get('author_username', 'unknown')
            text = tweet.get('text_content', '')
            # Truncate very long tweets
            if len(text) > DEFAULT_MAX_TWEET_LENGTH:
                text = text[:DEFAULT_MAX_TWEET_LENGTH] + "..."
            tweet_texts.append(f"Tweet {i+1} by @{author}: {text}")
        
        tweets_text = "\n\n".join(tweet_texts)
        
        # Create prompt
        prompt = f"""You are analyzing a collection of tweets from a user's home timeline. Your task is to categorize these tweets into meaningful, coherent categories based on their topics, themes, and content.

Here are the tweets to categorize:

{tweets_text}

Please analyze these tweets and group them into categories. Each category should:
1. Have a clear, descriptive name (e.g., "Technology & AI", "News & Politics", "Science", "Entertainment", "Sports", "Personal Updates", "Business & Finance", etc.)
2. Contain tweets that share a common theme or topic
3. Be specific enough to be useful, but broad enough to group related content

Return your response as a JSON object with this structure:
{{
  "categories": {{
    "Category Name 1": {{
      "description": "Brief description of what this category contains",
      "tweet_indices": [0, 3, 5, 7]
    }},
    "Category Name 2": {{
      "description": "Brief description of what this category contains",
      "tweet_indices": [1, 2, 4]
    }}
  }}
}}

The tweet_indices should be 0-based indices corresponding to the tweet numbers in the input (Tweet 1 = index 0, Tweet 2 = index 1, etc.).

Important:
- Every tweet should be assigned to at least one category
- Categories should be meaningful and distinct
- Aim for 5-10 categories depending on the diversity of content
- If a tweet fits multiple categories, assign it to the most relevant one
- Category names should be concise (2-5 words typically)

Return only the JSON object, no additional text."""
        
        try:
            if self.provider == 'anthropic':
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=DEFAULT_MAX_TOKENS_CATEGORIZE,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                )
                response_text = response.content[0].text
            else:  # openai
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    response_format={"type": "json_object"} if self.model.startswith('gpt-4') else None
                )
                response_text = response.choices[0].message.content
            
            # Try to extract JSON if there's extra text
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            
            # Parse JSON
            result = json.loads(response_text)
            
            # Convert indices to actual tweets
            categorized_tweets = {}
            for category_name, category_data in result.get('categories', {}).items():
                tweet_indices = category_data.get('tweet_indices', [])
                category_tweets = []
                for idx in tweet_indices:
                    if 0 <= idx < len(tweets):
                        category_tweets.append(tweets[idx])
                
                if category_tweets:
                    categorized_tweets[category_name] = {
                        'description': category_data.get('description', ''),
                        'tweets': category_tweets
                    }
            
            return categorized_tweets
            
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing AI response as JSON: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
            # Fallback: return all tweets in a single category
            return {
                "Uncategorized": {
                    'description': 'Tweets that could not be categorized',
                    'tweets': tweets
                }
            }
        except Exception as e:
            logger.error(f"Error categorizing tweets: {e}", exc_info=True)
            # Fallback: return all tweets in a single category
            return {
                "Uncategorized": {
                    'description': 'Tweets that could not be categorized',
                    'tweets': tweets
                }
            }
    
    def summarize_category(self, category_name: str, tweets: List[Dict]) -> str:
        """
        Generate a summary of tweets in a category with attribution.
        
        Args:
            category_name: Name of the category
            tweets: List of tweets in this category
        
        Returns:
            Summary text with attribution
        """
        if not tweets:
            return f"No tweets in {category_name}."
        
        # Initialize client if not already done
        self._initialize()
        
        # Prepare tweet data
        tweet_summaries = []
        for tweet in tweets:
            author = tweet.get('author_username', 'unknown')
            display_name = tweet.get('author_display_name', author)
            text = tweet.get('text_content', '')
            if len(text) > DEFAULT_MAX_TWEET_LENGTH_SUMMARY:
                text = text[:DEFAULT_MAX_TWEET_LENGTH_SUMMARY] + "..."
            tweet_summaries.append(f"@{author} ({display_name}): {text}")
        
        tweets_text = "\n\n".join(tweet_summaries)
        
        prompt = f"""You are summarizing tweets from the category "{category_name}". 

Here are the tweets:

{tweets_text}

Please create a concise summary (2-4 paragraphs) that:
1. Captures the main themes and topics discussed in these tweets
2. Mentions key authors and their contributions (use @username format)
3. Highlights interesting insights or discussions
4. Is engaging and informative

Format the summary with proper attribution to authors. For example:
"@author1 discusses X, while @author2 shares insights about Y..."

Return only the summary text, no additional formatting or labels."""
        
        try:
            if self.provider == 'anthropic':
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=DEFAULT_MAX_TOKENS_SUMMARY,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                )
                return response.content[0].text.strip()
            else:  # openai
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                )
                return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}", exc_info=True)
            # Fallback summary
            authors = set()
            for tweet in tweets:
                author = tweet.get('author_username', 'unknown')
                display_name = tweet.get('author_display_name', author)
                authors.add(f"@{author} ({display_name})")
            
            return f"This category contains {len(tweets)} tweets from {len(authors)} authors: {', '.join(sorted(authors))}."
