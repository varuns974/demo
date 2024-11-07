import streamlit as st
import boto3
import hashlib
import re
import logging
from config import (
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION,
    SETTINGS_TABLE_NAME, ADMIN_PASSWORD, BEDROCK_MODELS
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize AWS client
dynamodb = boto3.resource(
    'dynamodb',
    region_name=AWS_DEFAULT_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

def create_settings_table():
    table = dynamodb.create_table(
        TableName=SETTINGS_TABLE_NAME,
        KeySchema=[
            {'AttributeName': 'setting_name', 'KeyType': 'HASH'},
        ],
        AttributeDefinitions=[
            {'AttributeName': 'setting_name', 'AttributeType': 'S'},
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    table.wait_until_exists()
    return table

def get_or_create_settings_table():
    try:
        table = dynamodb.Table(SETTINGS_TABLE_NAME)
        table.load()
        return table
    except dynamodb.meta.client.exceptions.ResourceNotFoundException:
        return create_settings_table()

def get_setting(setting_name, default_value=None):
    table = get_or_create_settings_table()
    response = table.get_item(Key={'setting_name': setting_name})
    value = response.get('Item', {}).get('setting_value', default_value)
    logger.info(f"Retrieved setting: {setting_name} = {value}")
    return value

def update_setting(setting_name, setting_value):
    table = get_or_create_settings_table()
    table.put_item(Item={'setting_name': setting_name, 'setting_value': setting_value})
    logger.info(f"Updated setting: {setting_name} = {setting_value}")

def check_guardrails(text):
    blocked_words = get_setting('blocked_words', [])
    blocked_topics = get_setting('blocked_topics', [])
    
    logger.info(f"Checking text: {text}")
    logger.info(f"Blocked words: {blocked_words}")
    logger.info(f"Blocked topics: {blocked_topics}")
    
    for word in blocked_words:
        if re.search(r'\b' + re.escape(word) + r'\b', text, re.IGNORECASE):
            logger.info(f"Blocked word found: {word}")
            return False
    
    for topic in blocked_topics:
        if topic.lower() in text.lower():
            logger.info(f"Blocked topic found: {topic}")
            return False
    
    logger.info("No blocked words or topics found")
    return True

def admin_dashboard():
    st.title("Admin Dashboard")
    
    if 'admin_authenticated' not in st.session_state:
        st.session_state.admin_authenticated = False
    
    if not st.session_state.admin_authenticated:
        password = st.text_input("Enter admin password", type="password")
        if st.button("Login"):
            if hashlib.sha256(password.encode()).hexdigest() == hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest():
                st.session_state.admin_authenticated = True
                st.experimental_rerun()
            else:
                st.error("Incorrect password")
    else:
        st.write("Welcome to the Admin Dashboard")
        
        # Blocked Words
        st.subheader("Blocked Words")
        blocked_words = get_setting('blocked_words', [])
        new_blocked_word = st.text_input("Add a new blocked word")
        if st.button("Add Blocked Word"):
            blocked_words.append(new_blocked_word)
            update_setting('blocked_words', blocked_words)
            st.success(f"Added '{new_blocked_word}' to blocked words")
        
        st.write("Current Blocked Words:")
        for word in blocked_words:
            if st.button(f"Remove '{word}'"):
                blocked_words.remove(word)
                update_setting('blocked_words', blocked_words)
                st.experimental_rerun()
        
        # Blocked Topics
        st.subheader("Blocked Topics")
        blocked_topics = get_setting('blocked_topics', [])
        new_blocked_topic = st.text_input("Add a new blocked topic")
        if st.button("Add Blocked Topic"):
            blocked_topics.append(new_blocked_topic)
            update_setting('blocked_topics', blocked_topics)
            st.success(f"Added '{new_blocked_topic}' to blocked topics")
        
        st.write("Current Blocked Topics:")
        for topic in blocked_topics:
            if st.button(f"Remove '{topic}'"):
                blocked_topics.remove(topic)
                update_setting('blocked_topics', blocked_topics)
                st.experimental_rerun()

        # Model-specific settings
        st.subheader("Model Settings")
        model_settings = get_setting('model_settings', {})
        for model_name, model_id in BEDROCK_MODELS.items():
            st.write(f"Settings for {model_name} ({model_id})")
            temperature = st.slider(f"Temperature for {model_name}", 0.0, 1.0, model_settings.get(model_id, {}).get('temperature', 0.7), 0.1)
            max_tokens = st.number_input(f"Max Tokens for {model_name}", 100, 2000, model_settings.get(model_id, {}).get('max_tokens', 1000), 100)
            model_settings[model_id] = {'temperature': temperature, 'max_tokens': max_tokens}
        
        if st.button("Update Model Settings"):
            update_setting('model_settings', model_settings)
            st.success("Model settings updated successfully")        
        
        # Other Settings
        st.subheader("Other Settings")
        max_debate_duration = st.number_input("Maximum Debate Duration (seconds)", 
                                              value=int(get_setting('max_debate_duration', 180)))
        if st.button("Update Max Duration"):
            update_setting('max_debate_duration', max_debate_duration)
            st.success(f"Updated maximum debate duration to {max_debate_duration} seconds")

        # Test Guardrails
        st.subheader("Test Guardrails")
        test_text = st.text_input("Enter text to test against guardrails")
        if st.button("Test Guardrails"):
            result = check_guardrails(test_text)
            if result:
                st.success("Text passed guardrails check")
            else:
                st.error("Text failed guardrails check")

