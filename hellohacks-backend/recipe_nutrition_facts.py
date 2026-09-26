import requests
import os
from dotenv import load_dotenv

load_dotenv()
calorie_ninjas_key = os.getenv('CALORIE_NINJAS_KEY')

api_url = 'https://api.calorieninjas.com/v1/nutrition?query='
# placeholder query ; intended gemini output
query = '3lb carrots and a chicken sandwich'
response = requests.get(api_url + query, headers={'X-Api-Key': calorie_ninjas_key})
if response.status_code == requests.codes.ok:
    print(response.text)
else:
    print("Error:", response.status_code, response.text)