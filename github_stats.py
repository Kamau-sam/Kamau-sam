import datetime
from dateutil import relativedelta
import requests
import os
from xml.dom import minidom
import time
import hashlib
from dotenv import load_dotenv
import json
from pathlib import Path
import logging
from typing import Dict, List, Optional, Union
from tqdm import tqdm

class GitHubStats:
    def __init__(self, access_token: Optional[str] = None, user_name: Optional[str] = None):
        """
        Initialize GitHub Statistics generator.
        
        Args:
            access_token (str, optional): GitHub access token
            user_name (str, optional): GitHub username
        
        Raises:
            EnvironmentError: If credentials cannot be found
        """
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('github_stats.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Load environment variables
        load_dotenv()
        
        # Initialize credentials with fallbacks
        self.access_token = self._get_credential(
            access_token,
            ['GITHUB_ACCESS_TOKEN', 'ACCESS_TOKEN'],
            "GitHub access token",
            "https://github.com/settings/tokens"
        )
        
        self.user_name = self._get_credential(
            user_name,
            ['GITHUB_USERNAME', 'USER_NAME'],
            "GitHub username"
        )
            
        self.headers = {
            'Authorization': f'token {self.access_token}',
            'Accept': 'application/vnd.github.v4+json'
        }
        
        # Validate token immediately
        self._validate_token()
        
        # Configure cache
        self.cache_dir = Path('cache')
        self.cache_dir.mkdir(exist_ok=True)
        
        # Initialize rate limiting tracker
        self.query_count: Dict[str, int] = {
            'user_getter': 0,
            'follower_getter': 0,
            'graph_repos_stars': 0,
            'recursive_loc': 0,
            'graph_commits': 0,
            'loc_query': 0
        }
        
        self.logger.info(f"GitHubStats initialized for user: {self.user_name}")

    def _validate_token(self) -> None:
        """
        Validate GitHub token by making test requests to verify permissions.
        
        Raises:
            Exception: If token is invalid or has insufficient permissions
        """
        try:
            # Test basic authentication
            user_response = requests.get(
                'https://api.github.com/user',
                headers=self.headers,
                timeout=10
            )
            
            if user_response.status_code == 401:
                raise Exception(
                    "Invalid GitHub token. Please check your token and ensure it has the required permissions:\n"
                    "- repo (Full control of private repositories)\n"
                    "- read:user (Read ALL user profile data)\n"
                    "- user:email (Access user email addresses)\n"
                    "- read:org (Read org and team membership)"
                )
            user_response.raise_for_status()
            
            # Verify repository access
            query = """
            query {
              viewer {
                repositories(first: 1, privacy: PRIVATE) {
                  nodes {
                    nameWithOwner
                    isPrivate
                  }
                }
              }
            }
            """
            
            repo_response = requests.post(
                'https://api.github.com/graphql',
                json={'query': query},
                headers=self.headers,
                timeout=10
            )
            
            if repo_response.status_code != 200:
                raise Exception("Unable to access repository data. Check if token has 'repo' scope.")
                
            repo_data = repo_response.json()
            if 'errors' in repo_data:
                raise Exception(
                    "Insufficient permissions to access private repositories. "
                    "Please ensure your token has the 'repo' scope."
                )
                
            # Verify user data access
            user_data = user_response.json()
            if user_data.get('login') != self.user_name:
                self.logger.warning(
                    f"Token belongs to user '{user_data.get('login')}' "
                    f"but username is set to '{self.user_name}'. "
                    "This might cause unexpected behavior."
                )
                
            self.logger.info("Successfully validated token with full repository access")
                
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to validate GitHub token: {str(e)}")

    def _get_credential(
        self,
        direct_value: Optional[str],
        env_keys: List[str],
        credential_name: str,
        help_url: Optional[str] = None
    ) -> str:
        """
        Get credential with multiple fallbacks and helpful error messages.
        
        Args:
            direct_value: Directly provided credential value
            env_keys: List of environment variable keys to check
            credential_name: Name of the credential for error messages
            help_url: Optional URL for getting the credential
            
        Returns:
            str: The credential value
            
        Raises:
            EnvironmentError: If credential cannot be found
        """
        # Check direct value
        if direct_value:
            return direct_value
            
        # Check environment variables
        for key in env_keys:
            value = os.getenv(key)
            if value:
                return value.strip()  # Added strip() to remove any whitespace
                
        # Build error message
        error_msg = [
            f"{credential_name} not found. Please either:",
            f"1. Set any of these environment variables: {', '.join(env_keys)}",
            f"2. Create a .env file with {env_keys[0]}=your_value",
            f"3. Pass {env_keys[0].lower()} parameter to GitHubStats()"
        ]
        
        if help_url:
            error_msg.append(f"\nTo create a {credential_name}, visit: {help_url}")
            
        raise EnvironmentError("\n".join(error_msg))

    def _cache_key(self, query: str, variables: Dict) -> str:
        """Generate cache key for a query."""
        return hashlib.sha256(
            f"{query}{str(variables)}".encode()
        ).hexdigest()

    def _get_cached_response(self, cache_key: str) -> Optional[Dict]:
        """Get cached response if available."""
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                with cache_file.open('r') as f:
                    data = json.load(f)
                    self.logger.debug(f"Cache hit for key: {cache_key[:8]}...")
                    return data
            except json.JSONDecodeError:
                self.logger.warning(f"Corrupted cache file found: {cache_file}")
                cache_file.unlink()
        return None

    def _cache_response(self, cache_key: str, response_data: Dict) -> None:
        """Cache API response."""
        cache_file = self.cache_dir / f"{cache_key}.json"
        with cache_file.open('w') as f:
            json.dump(response_data, f)
        self.logger.debug(f"Cached response for key: {cache_key[:8]}...")

    def simple_request(self, func_name: str, query: str, variables: Dict) -> Dict:
        """
        Make a GraphQL request with comprehensive error handling and caching.
        """
        cache_key = self._cache_key(query, variables)
        
        # Check cache first
        cached_data = self._get_cached_response(cache_key)
        if cached_data:
            return cached_data
            
        try:
            # Add delay to avoid rate limiting
            time.sleep(0.5)
            
            response = requests.post(
                'https://api.github.com/graphql',
                json={'query': query, 'variables': variables},
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 403:
                reset_time = response.headers.get('X-RateLimit-Reset')
                if reset_time:
                    wait_time = int(reset_time) - int(time.time())
                    raise Exception(
                        f"Rate limit exceeded. Reset in {wait_time} seconds."
                    )
                raise Exception("Rate limit exceeded. Please wait before trying again.")
                
            response.raise_for_status()
            data = response.json()
            
            # Check for GraphQL errors
            if 'errors' in data:
                errors = data['errors']
                error_messages = [e.get('message', 'Unknown error') for e in errors]
                raise Exception(f"GraphQL errors: {'; '.join(error_messages)}")
            
            # Cache successful response
            self._cache_response(cache_key, data)
            return data
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"{func_name} request failed: {str(e)}")
            raise Exception(f"{func_name} failed: {str(e)}")

    def daily_readme(self, start_date: datetime.datetime) -> int:
        """Calculate uptime since start date."""
        today = datetime.datetime.now()
        delta = today - start_date
        return delta.days

    def get_repositories(self, affiliation_types: List[str]) -> List[Dict]:
        """Fetch repositories based on affiliation type."""
        query = """
        query($cursor: String) {
          viewer {
            repositories(
              first: 100
              after: $cursor
              affiliations: [%s]
              isFork: false
            ) {
              nodes {
                nameWithOwner
                stargazerCount
                isPrivate
                defaultBranchRef {
                  target {
                    ... on Commit {
                      history {
                        totalCount
                      }
                    }
                  }
                }
              }
              pageInfo {
                hasNextPage
                endCursor
              }
            }
          }
        }
        """ % ", ".join(affiliation_types)

        repositories = []
        variables = {"cursor": None}

        while True:
            response = self.simple_request(
                "get_repositories",
                query,
                variables
            )
            
            repo_data = response['data']['viewer']['repositories']
            repositories.extend(repo_data['nodes'])
            
            if not repo_data['pageInfo']['hasNextPage']:
                break
                
            variables['cursor'] = repo_data['pageInfo']['endCursor']

        return repositories

    def calculate_loc(self, repo: Dict) -> Dict[str, int]:
        """Calculate lines of code statistics for a repository."""
        query = """
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            defaultBranchRef {
              target {
                ... on Commit {
                  additions
                  deletions
                }
              }
            }
          }
        }
        """
        
        owner, name = repo['nameWithOwner'].split('/')
        variables = {
            "owner": owner,
            "name": name
        }
        
        response = self.simple_request(
            "calculate_loc",
            query,
            variables
        )
        
        commit_data = response['data']['repository']['defaultBranchRef']['target']
        
        return {
            'additions': commit_data['additions'],
            'deletions': commit_data['deletions'],
            'total': commit_data['additions'] - commit_data['deletions']
        }

    def get_followers(self) -> int:
        """Get follower count for the authenticated user."""
        query = """
        query {
          viewer {
            followers {
              totalCount
            }
          }
        }
        """
        
        response = self.simple_request(
            "get_followers",
            query,
            {}
        )
        
        return response['data']['viewer']['followers']['totalCount']

    def generate_stats(self) -> Dict:
        """
        Generate comprehensive GitHub statistics for the user.
        
        Returns:
            Dict containing various GitHub statistics including:
            - Repository count (total, public, private)
            - Total stars
            - Lines of code
            - Follower count
            - Contribution statistics
        """
        self.logger.info("Beginning stats generation...")
        
        try:
            # Get repositories
            repos = self.get_repositories(['OWNER', 'COLLABORATOR'])
            
            # Calculate basic stats
            public_repos = [repo for repo in repos if not repo['isPrivate']]
            private_repos = [repo for repo in repos if repo['isPrivate']]
            
            stats = {
                'repository_count': {
                    'total': len(repos),
                    'public': len(public_repos),
                    'private': len(private_repos)
                },
                'stars': {
                    'total': sum(repo['stargazerCount'] for repo in repos),
                    'public': sum(repo['stargazerCount'] for repo in public_repos),
                    'private': sum(repo['stargazerCount'] for repo in private_repos)
                },
                'followers': self.get_followers()
            }
            
            # Calculate LOC stats
            def calculate_repo_stats(repositories):
                loc_stats = {'additions': 0, 'deletions': 0, 'total': 0}
                for repo in repositories:
                    try:
                        repo_loc = self.calculate_loc(repo)
                        for key in loc_stats:
                            loc_stats[key] += repo_loc[key]
                    except Exception as e:
                        self.logger.warning(f"Failed to calculate LOC for {repo['nameWithOwner']}: {str(e)}")
                return loc_stats
            
            self.logger.info("Calculating public repository statistics...")
            stats['lines_of_code'] = {
                'public': calculate_repo_stats(public_repos),
                'private': calculate_repo_stats(private_repos)
            }
            
            # Add total LOC
            stats['lines_of_code']['total'] = {
                key: stats['lines_of_code']['public'][key] + stats['lines_of_code']['private'][key]
                for key in ['additions', 'deletions', 'total']
            }
            
            # Calculate account age
            start_date = datetime.datetime(2020, 1, 1)  # Replace with actual account creation date
            stats['account_age_days'] = self.daily_readme(start_date)
            
            self.logger.info("Stats generation completed successfully")
            return stats
            
        except Exception as e:
            self.logger.error(f"Failed to generate stats: {str(e)}")
            raise

if __name__ == '__main__':
    try:
        generator = GitHubStats()
        stats = generator.generate_stats()
        print("\nGitHub Statistics:")
        print(json.dumps(stats, indent=2))
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        print("\nPlease check that:")
        print("1. You have created a .env file with your GitHub token")
        print("2. The token has the required permissions:")
        print("   - repo (Full control of private repositories)")
        print("   - read:user (Read ALL user profile data)")
        print("   - user:email (Access user email addresses)")
        print("   - read:org (Read org and team membership)")
        print("3. Your username is correct")
        print("\nFor detailed error information, check github_stats.log")