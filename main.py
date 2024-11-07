import streamlit as st
import boto3
import json
import time
import uuid
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError
from contextlib import closing
import re
import random
from config import (
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION,
    DEBATE_TABLE_NAME, BEDROCK_MODELS, POLLY_VOICE_TIM, POLLY_VOICE_TINA, DEBUG
)
from admin_dashboard import admin_dashboard, get_setting, check_guardrails
from model_analytics import run_analytics_dashboard

# Initialize AWS clients
bedrock = boto3.client(
    service_name='bedrock-runtime',
    region_name=AWS_DEFAULT_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)
dynamodb = boto3.resource(
    'dynamodb',
    region_name=AWS_DEFAULT_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)
polly = boto3.client(
    'polly',
    region_name=AWS_DEFAULT_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

def create_debate_table():
    table = dynamodb.create_table(
        TableName=DEBATE_TABLE_NAME,
        KeySchema=[
            {'AttributeName': 'debate_id', 'KeyType': 'HASH'},
            {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'debate_id', 'AttributeType': 'S'},
            {'AttributeName': 'timestamp', 'AttributeType': 'N'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    table.wait_until_exists()
    return table

def get_or_create_table():
    try:
        table = dynamodb.Table(DEBATE_TABLE_NAME)
        table.load()
        return table
    except dynamodb.meta.client.exceptions.ResourceNotFoundException:
        return create_debate_table()

def store_debate(topic, debate_json, judgment, audio_files, model_a, model_b):
    table = get_or_create_table()
    debate_id = str(uuid.uuid4())
    timestamp = int(time.time())
    
    item = {
        'debate_id': debate_id,
        'timestamp': timestamp,
        'topic': topic,
        'debate_data': json.dumps(debate_json),
        'judgment': json.dumps(judgment),
        'audio_files': json.dumps(audio_files),
        'model_a': model_a,
        'model_b': model_b
    }
    
    table.put_item(Item=item)
    return debate_id

def converse_with_model(messages, model_id):
    model_settings = get_setting('model_settings', {}).get(model_id, {})
    temperature = model_settings.get('temperature', 0.7)
    max_tokens = model_settings.get('max_tokens', 1000)

    # Combine all user messages and ensure alternating roles
    combined_messages = []
    user_content = ""
    for msg in messages:
        if msg['role'] == 'user':
            user_content += msg['content'] + "\n\n"
        elif msg['role'] == 'assistant':
            if user_content:
                combined_messages.append({'role': 'user', 'content': user_content.strip()})
                user_content = ""
            combined_messages.append(msg)
    
    if user_content:
        combined_messages.append({'role': 'user', 'content': user_content.strip()})
    
    # Ensure the conversation starts with a user message
    if combined_messages and combined_messages[0]['role'] == 'assistant':
        combined_messages.insert(0, {'role': 'user', 'content': 'Hello'})

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": combined_messages,
        "temperature": temperature,
    }

    try:
        response = bedrock.invoke_model(
            body=json.dumps(body),
            modelId=model_id,
            accept='application/json',
            contentType='application/json'
        )
        
        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']

    except Exception as e:
        print(f"Error in converse_with_model: {str(e)}")
        return f"Error: {str(e)}"

def generate_debate_point(topic, participant, side, model_id, round_num, previous_points):
    context = f"Previous arguments:\n{previous_points}\n\n" if previous_points else ""
    
    messages = [
        {"role": "user", "content": f"""You are an AI assistant participating in a debate. Your role is to provide concise, persuasive arguments.

{context}You are {participant} in a debate on the topic: '{topic}'. 
You are arguing that {side}. This is round {round_num} of 3. 
First, briefly acknowledge the previous point made by the other participant (if any). 
Then, provide a concise, 20-second argument (approximately 50 words) that supports your side 
and is different from any previous arguments. Focus on a new aspect or counterargument. 
Respond with only the argument, no additional context or meta-information."""}
    ]
    
    debate_point = converse_with_model(messages, model_id)
    cleaned_point = re.sub(r'^(Tim:|Tina:|Here\'s my argument:?\s*)', '', debate_point).strip()
    st.markdown(f"**{participant}:** {cleaned_point}")
    time.sleep(1)
    return cleaned_point

def judge_debate(debate_json, model_id, side_tim, side_tina):
    messages = [
        {"role": "user", "content": f"""You are an impartial judge evaluating a debate. Provide a fair assessment based on the arguments presented.

Judge the following debate and determine the winner based on the strength of arguments, clarity, and persuasiveness. You must choose either Tim or Tina as the winner. Provide your judgment in this format:
Winner: [Tim or Tina]
Reasoning: [Your brief explanation]

Tim's arguments (arguing that {side_tim}):
1. {debate_json['tim'][0]}
2. {debate_json['tim'][1]}
3. {debate_json['tim'][2]}

Tina's arguments (arguing that {side_tina}):
1. {debate_json['tina'][0]}
2. {debate_json['tina'][1]}
3. {debate_json['tina'][2]}"""}
    ]
    
    st.write("Judging the debate...")
    response = converse_with_model(messages, model_id)
    
    winner_match = re.search(r'Winner:\s*(Tim|Tina)', response)
    reasoning_match = re.search(r'Reasoning:\s*(.*)', response, re.DOTALL)
    
    winner = winner_match.group(1) if winner_match else "Tim" if random.random() < 0.5 else "Tina"
    reasoning = reasoning_match.group(1).strip() if reasoning_match else "Both participants presented strong arguments."
    
    judgment = {
        "winner": winner,
        "reasoning": reasoning
    }
    
    winner_side = side_tim if winner == "Tim" else side_tina
    summary = f"{winner} won the debate, arguing that {winner_side}."
    
    return judgment, summary

def generate_debate(topic, model_a, model_b):
    debate_json = {"tim": [], "tina": []}
    st.session_state.audio_files = []
    
    entities = parse_topic(topic)
    if entities:
        entity1, entity2 = entities
        tim_stance = f"{entity1} is better than {entity2}"
        tina_stance = f"{entity2} is better than {entity1}"
    else:
        tim_stance = f"in favor of {topic}"
        tina_stance = f"against {topic}"

    st.subheader("Debate Arguments")
    st.write(f"Topic: {topic}")
    st.write(f"Tim is arguing that {tim_stance}.")
    st.write(f"Tina is arguing that {tina_stance}.")
    st.markdown("---")

    for i in range(3):
        st.write(f"**Round {i+1}**")
        
        previous_points_tim = "\n".join(debate_json["tim"] + debate_json["tina"])
        st.write("Tim's turn...")
        point_tim = generate_debate_point(topic, "Tim", tim_stance, model_a, i+1, previous_points_tim)
        debate_json["tim"].append(point_tim)
        generate_and_play_audio(point_tim, "Tim")
        time.sleep(1)
        
        previous_points_tina = "\n".join(debate_json["tim"] + debate_json["tina"])
        st.write("Tina's turn...")
        point_tina = generate_debate_point(topic, "Tina", tina_stance, model_b, i+1, previous_points_tina)
        debate_json["tina"].append(point_tina)
        generate_and_play_audio(point_tina, "Tina")
        time.sleep(1)
        
        if i < 2:
            st.markdown("---")
    
    return debate_json, tim_stance, tina_stance

def text_to_speech(text, output_file, voice_id):
    try:
        response = polly.synthesize_speech(
            Text=text,
            OutputFormat="mp3",
            VoiceId=voice_id
        )

        if "AudioStream" in response:
            with closing(response["AudioStream"]) as stream:
                with open(output_file, "wb") as file:
                    file.write(stream.read())
    except (BotoCoreError, ClientError) as error:
        print(f"Error generating audio: {error}")
        return None

    return output_file

def generate_and_play_audio(text, participant):
    voice_id = POLLY_VOICE_TIM if participant == "Tim" else POLLY_VOICE_TINA
    file_name = f"audio/{participant.lower()}_round_{len(st.session_state.audio_files) // 2 + 1}.mp3"
    audio_file = text_to_speech(text, file_name, voice_id)
    if audio_file:
        st.audio(audio_file)
        st.session_state.audio_files.append(audio_file)

def parse_topic(topic):
    entities = re.findall(r'(\w+(?:\s+\w+)*)\s+(?:or|vs\.?|versus)\s+(\w+(?:\s+\w+)*)', topic, re.IGNORECASE)
    if entities:
        return entities[0]
    else:
        return None

def debate_generator():
    st.title("AI Debate Generator and Judge")

    topic = st.text_input("Enter a debate topic:")

    col1, col2, col3 = st.columns(3)
    with col1:
        model_a = st.selectbox("Select Model for Tim", list(BEDROCK_MODELS.keys()), index=0)
    with col2:
        model_b = st.selectbox("Select Model for Tina", list(BEDROCK_MODELS.keys()), index=1)
    with col3:
        judge_model = st.selectbox("Select Model for Judge", list(BEDROCK_MODELS.keys()), index=0)

    if st.button("Generate Debate"):
        if not check_guardrails(topic):
            st.error("The topic contains blocked words or topics. Please choose a different topic.")
            return
        
        debate_json, side_tim, side_tina = generate_debate(topic, BEDROCK_MODELS[model_a], BEDROCK_MODELS[model_b])

        total_duration = sum(len(arg.split()) for args in debate_json.values() for arg in args) / 150 * 60
        max_duration = get_setting('max_debate_duration', 180)
        if total_duration > max_duration:
            st.warning(f"The debate exceeds the maximum allowed duration of {max_duration} seconds. Some content may be truncated.")

        st.write(f"Estimated total debate duration: {min(total_duration, max_duration):.2f} seconds")

        st.subheader("Judging the Debate")
        judgment, summary = judge_debate(debate_json, BEDROCK_MODELS[judge_model], side_tim, side_tina)

        st.subheader("Debate Result")
        st.write(f"Winner: {judgment['winner']}")
        st.write(f"Reasoning: {judgment['reasoning']}")
        st.write(f"Summary: {summary}")

        debate_id = store_debate(topic, debate_json, judgment, st.session_state.audio_files, model_a, model_b)
        st.success(f"Debate stored with ID: {debate_id}")

def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Debate Generator", "Admin Dashboard", "Model Analytics"])

    if page == "Debate Generator":
        debate_generator()
    elif page == "Admin Dashboard":
        admin_dashboard()
    elif page == "Model Analytics":
        run_analytics_dashboard(DEBATE_TABLE_NAME)

    if DEBUG:
        st.sidebar.title("Debug Information")
        st.sidebar.write(f"AWS Region: {AWS_DEFAULT_REGION}")
        st.sidebar.write(f"DynamoDB Table: {DEBATE_TABLE_NAME}")
        st.sidebar.write(f"Polly Voices: Tim - {POLLY_VOICE_TIM}, Tina - {POLLY_VOICE_TINA}")

if __name__ == "__main__":
    main()