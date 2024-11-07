import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# AWS configuration
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_DEFAULT_REGION = os.getenv('AWS_DEFAULT_REGION')
DEBATE_TABLE_NAME = os.getenv('DYNAMODB_TABLE_NAME')
SETTINGS_TABLE_NAME = os.getenv('SETTINGS_TABLE_NAME', 'DebateAppSettings')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')  # Change this to a secure password

# Available Bedrock models
BEDROCK_MODELS = {
    "Claude 3 Sonnet": "anthropic.claude-3-sonnet-20240229-v1:0",
    "Claude 2": "anthropic.claude-v2:1",
    "Claude Instant": "anthropic.claude-instant-v1",
    "Titan Text": "amazon.titan-text-express-v1"
}

# Polly voices
POLLY_VOICE_TIM = 'Matthew'
POLLY_VOICE_TINA = 'Joanna'

# Debug mode
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'