"""
Service for generating AI summaries of events from tweets.
"""
import os
import logging
from typing import List, Tuple
from decouple import config

logger = logging.getLogger(__name__)

# Constants
DEFAULT_MAX_TWEETS_FOR_SUMMARY = 50
DEFAULT_MAX_KEYWORDS_FOR_SUMMARY = 10
DEFAULT_MAX_HEADLINE_LENGTH = 500
DEFAULT_MAX_SUMMARY_LENGTH = 2000
DEFAULT_MAX_TOKENS_ANTHROPIC = 1000
DEFAULT_MAX_TOKENS_OPENAI = 500


class SummarizationService:
    """Service for generating event summaries using AI."""
    
    def __init__(self):
        """Initialize the summarization service."""
        # Check for API keys - prefer OpenAI, fallback to Anthropic
        self.openai_api_key = config('OPENAI_API_KEY', default=None)
        self.anthropic_api_key = config('ANTHROPIC_API_KEY', default=None)
        self.openai_model = config('OPENAI_MODEL', default='gpt-4o-mini')
        self.anthropic_model = config('ANTHROPIC_MODEL', default='claude-sonnet-4-20250514')
        
        # Determine which provider to use
        if self.openai_api_key:
            self.provider = 'openai'
        elif self.anthropic_api_key:
            self.provider = 'anthropic'
        else:
            self.provider = None
    
    def _generate_with_anthropic(self, texts: List[str], keywords: List[str]) -> Tuple[str, str]:
        """Generate headline and summary using Anthropic Claude API."""
        try:
            from anthropic import Anthropic
            
            client = Anthropic(api_key=self.anthropic_api_key)
            
            # Combine tweets into context
            tweets_context = "\n\n".join([
                f"Tweet {i+1}: {text}" for i, text in enumerate(texts[:50])  # Limit to 50 tweets
            ])
            
            keywords_str = ", ".join(keywords[:10])
            
            prompt = f"""You are analyzing a collection of tweets about a specific event or topic. Based on the following tweets and keywords, generate:

1. A concise, engaging headline (max 100 characters) that captures the main event or topic
2. A comprehensive summary (2-4 paragraphs) that synthesizes the key information from all the tweets

Keywords identified: {keywords_str}

Tweets:
{tweets_context}

Please provide:
- Headline: [your headline here]
- Summary: [your summary here]

Format your response exactly as:
HEADLINE: [headline text]
SUMMARY: [summary text]"""
            
            response = client.messages.create(
                model=self.anthropic_model,
                max_tokens=DEFAULT_MAX_TOKENS_ANTHROPIC,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            
            content = response.content[0].text
            
            # Parse response
            lines = content.split('\n')
            headline = ""
            summary_parts = []
            in_summary = False
            
            for line in lines:
                line = line.strip()
                if line.startswith('HEADLINE:'):
                    headline = line.replace('HEADLINE:', '').strip()
                elif line.startswith('SUMMARY:'):
                    summary_parts.append(line.replace('SUMMARY:', '').strip())
                    in_summary = True
                elif in_summary and line:
                    summary_parts.append(line)
            
            summary = ' '.join(summary_parts) if summary_parts else content
            
            # Fallback if parsing failed
            if not headline:
                headline = keywords[0].title() if keywords else "Event"
            if not summary:
                summary = content[:500] if content else "Summary unavailable."
            
            return headline[:500], summary[:2000]  # Enforce max lengths
            
        except ImportError:
            raise Exception("Anthropic package not installed. Install with: pip install anthropic")
        except Exception as e:
            raise Exception(f"Error generating summary with Anthropic: {e}")
    
    def _generate_with_openai(self, texts: List[str], keywords: List[str]) -> Tuple[str, str]:
        """Generate headline and summary using OpenAI API."""
        try:
            from openai import OpenAI
            
            client = OpenAI(api_key=self.openai_api_key)
            
            # Combine tweets into context
            tweets_context = "\n\n".join([
                f"Tweet {i+1}: {text}" for i, text in enumerate(texts[:50])  # Limit to 50 tweets
            ])
            
            keywords_str = ", ".join(keywords[:10])
            
            prompt = f"""You are analyzing a collection of tweets about a specific event or topic. Based on the following tweets and keywords, generate:

1. A concise, engaging headline (max 100 characters) that captures the main event or topic
2. A comprehensive summary (2-4 paragraphs) that synthesizes the key information from all the tweets

Keywords identified: {keywords_str}

Tweets:
{tweets_context}

Please provide:
- Headline: [your headline here]
- Summary: [your summary here]

Format your response exactly as:
HEADLINE: [headline text]
SUMMARY: [summary text]"""
            
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that creates concise, informative summaries of social media events."},
                    {"role": "user", "content": prompt}
                ],
                    temperature=0.7,
                    max_tokens=DEFAULT_MAX_TOKENS_OPENAI
            )
            
            content = response.choices[0].message.content
            
            # Parse response
            lines = content.split('\n')
            headline = ""
            summary_parts = []
            in_summary = False
            
            for line in lines:
                line = line.strip()
                if line.startswith('HEADLINE:'):
                    headline = line.replace('HEADLINE:', '').strip()
                elif line.startswith('SUMMARY:'):
                    summary_parts.append(line.replace('SUMMARY:', '').strip())
                    in_summary = True
                elif in_summary and line:
                    summary_parts.append(line)
            
            summary = ' '.join(summary_parts) if summary_parts else content
            
            # Fallback if parsing failed
            if not headline:
                headline = keywords[0].title() if keywords else "Event"
            if not summary:
                summary = content[:500] if content else "Summary unavailable."
            
            return headline[:500], summary[:2000]  # Enforce max lengths
            
        except ImportError:
            raise Exception("OpenAI package not installed. Install with: pip install openai")
        except Exception as e:
            raise Exception(f"Error generating summary with OpenAI: {e}")
    
    def _generate_fallback(self, texts: List[str], keywords: List[str]) -> Tuple[str, str]:
        """Generate a simple fallback summary without AI."""
        # Use first tweet as basis for headline
        first_text = texts[0] if texts else ""
        headline = first_text[:100] + "..." if len(first_text) > 100 else first_text
        
        # Create simple summary
        summary_parts = [
            f"This event includes {len(texts)} related tweets.",
            f"Key topics: {', '.join(keywords[:5])}.",
            "Summary generation requires an AI API key (OpenAI or Anthropic) to be configured."
        ]
        
        summary = " ".join(summary_parts)
        
        return headline, summary
    
    def generate_event_summary(self, texts: List[str], keywords: List[str]) -> Tuple[str, str]:
        """
        Generate a headline and summary for an event from a list of tweets.
        
        Args:
            texts: List of tweet texts
            keywords: List of extracted keywords
        
        Returns:
            Tuple of (headline, summary)
        """
        if not texts:
            return "No Event", "No tweets available for this event."
        
        # Try OpenAI first if available
        if self.provider == 'openai':
            try:
                return self._generate_with_openai(texts, keywords)
            except Exception as e:
                logger.warning(f"OpenAI summarization failed: {e}, trying Anthropic fallback")
                # Fallback to Anthropic if OpenAI fails
                if self.anthropic_api_key:
                    try:
                        return self._generate_with_anthropic(texts, keywords)
                    except Exception as e2:
                        logger.warning(f"Anthropic summarization also failed: {e2}, using basic fallback")
                        return self._generate_fallback(texts, keywords)
                else:
                    return self._generate_fallback(texts, keywords)
        
        # Try Anthropic if OpenAI not available
        elif self.provider == 'anthropic':
            try:
                return self._generate_with_anthropic(texts, keywords)
            except Exception as e:
                logger.warning(f"Anthropic summarization failed: {e}, using fallback")
                return self._generate_fallback(texts, keywords)
        
        # No API keys available
        else:
            return self._generate_fallback(texts, keywords)
