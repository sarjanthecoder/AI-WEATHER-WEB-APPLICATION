import os
import json
import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import google.generativeai as genai
from flask_cors import CORS
from urllib.parse import quote

# --- SETUP ---
load_dotenv()
app = Flask(__name__)
# This allows your HTML file to communicate with this backend
CORS(app)

@app.route('/')
def index():
    return render_template('index.html')

# --- API CONFIGURATION ---
try:
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set.")
    genai.configure(api_key=gemini_api_key)
    gemini_model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    print(f"Error configuring Gemini: {e}")
    gemini_model = None

# --- NEW GEOCODING ENDPOINT ---
@app.route('/geocode', methods=['GET'])
def geocode_city():
    city_name = request.args.get('q')
    if not city_name:
        return jsonify({"error": "City name 'q' is required"}), 400
    
    try:
        openweather_key = os.getenv('OPENWEATHER_API_KEY')
        if not openweather_key:
            raise ValueError("OPENWEATHER_API_KEY environment variable not set.")
        geocode_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city_name}&limit=1&appid={openweather_key}"
        response = requests.get(geocode_url)
        response.raise_for_status()
        data = response.json()
        if not data:
            return jsonify({"error": f"Could not find coordinates for city: {city_name}"}), 404
        
        return jsonify(data[0])
    except requests.exceptions.RequestException as e:
        print(f"Geocoding API Error: {e}")
        return jsonify({"error": "Failed to connect to the geocoding service."}), 500
    except ValueError as e:
        print(f"Configuration Error: {e}")
        return jsonify({"error": str(e)}), 500

# --- MAIN DATA ENDPOINT ---
@app.route('/get-weather-pro-data', methods=['GET'])
def get_weather_pro_data():
    lat = request.args.get('lat')
    lon = request.args.get('lon')

    if not lat or not lon:
        return jsonify({"error": "Latitude and longitude are required"}), 400

    try:
        openweather_key = os.getenv('OPENWEATHER_API_KEY')
        if not openweather_key:
            raise ValueError("OPENWEATHER_API_KEY environment variable not set.")
        weather_url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&appid={openweather_key}&units=metric&exclude=minutely"
        weather_response = requests.get(weather_url)
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        current_weather = weather_data['current']
        city_name = get_city_name(lat, lon, openweather_key)
        weather_condition = current_weather['weather'][0]['main']
        temperature = current_weather['temp']
        
        rain_alert = "No immediate rain expected."
        if 'hourly' in weather_data:
            for hour in weather_data['hourly'][:3]:
                if hour['weather'][0]['main'].lower() == 'rain':
                    rain_alert = f"Heads up! Rain is expected within the next 3 hours."
                    break

        if not gemini_model:
            raise Exception("Gemini model is not initialized.")
            
        prompt = f"""
        Based on the weather in {city_name}, which is currently "{weather_condition}" at {temperature}°C:
        1.  Provide a one-sentence, stylish clothing recommendation.
        2.  Provide a one-sentence food recommendation that fits the weather.
        3.  Suggest a specific, relevant product category a person might need to buy.
        4.  Suggest a popular tourist place in or near {city_name} that is suitable for the current weather.
        5.  Provide a one-sentence travel advice for the recommended tourist place.
        Strictly return the response as a single, valid JSON object with keys: "clothing", "food", "product", "tourist_place", "tourist_advice".
        Example: {{"clothing": "...", "food": "...", "product": "...", "tourist_place": "...", "tourist_advice": "..."}}
        """
        ai_response = gemini_model.generate_content(prompt)
        response_text = ai_response.text.strip().replace("```json", "").replace("```", "")
        recommendations = json.loads(response_text)

        # Get generic image for the city itself for tourist recommendations
        clothing_img_url = get_pixabay_image(recommendations.get("clothing"))
        food_img_url = get_pixabay_image(recommendations.get("food"))
        tourist_img_url = get_pixabay_image(city_name) # Fetch image based on city name for better results

        product_query = quote(recommendations.get("product", ""))
        shopping_links = {
            "amazon": f"https://www.amazon.in/s?k={product_query}",
            "flipkart": f"https://www.flipkart.com/search?q={product_query}"
        }

        final_data = {
            "city": city_name,
            "current": weather_data['current'],
            "daily": weather_data.get('daily', []),
            "rain_alert": rain_alert,
            "recommendations": {
                "clothing": {"text": recommendations.get("clothing"), "image": clothing_img_url},
                "food": {"text": recommendations.get("food"), "image": food_img_url},
                "product": {"text": recommendations.get("product"), "links": shopping_links},
                "tourist": {"text": recommendations.get("tourist_advice"), "image": tourist_img_url}
            }
        }
        return jsonify(final_data)

    except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as e:
        print(f"ERROR in get_weather_pro_data: {e}")
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({"error": "An unexpected error occurred."}), 500

# --- CHATBOT ENDPOINT ---
@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    if not user_message:
        return jsonify({"error": "Message is required"}), 400
    if not gemini_model:
        return jsonify({"reply": "Sorry, the AI assistant is currently unavailable."})

    try:
        prompt = f"You are WeatherPro AI, a friendly and helpful assistant for a weather app. A user asked: '{user_message}'. Answer concisely and helpfully."
        response = gemini_model.generate_content(prompt)
        return jsonify({"reply": response.text})
    except Exception as e:
        print(f"ERROR in chat: {e}")
        return jsonify({"error": str(e)}), 500

# --- HELPER FUNCTIONS ---
def get_pixabay_image(query):
    if not query: 
        return ""
    pixabay_key = os.getenv('PIXABAY_API_KEY')
    if not pixabay_key:
        print("PIXABAY_API_KEY environment variable not set.")
        return ""
    try:
        url = f"https://pixabay.com/api/?key={pixabay_key}&q={quote(query)}&image_type=photo&per_page=3&safesearch=true"
        response = requests.get(url)
        response.raise_for_status()
        images = response.json().get("hits", [])
        return images[0]['webformatURL'] if images else ""
    except Exception as e:
        print(f"Pixabay Error: {e}")
        return ""

def get_city_name(lat, lon, api_key):
    try:
        url = f"http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={lon}&limit=1&appid={api_key}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data[0]['name'] if data else "Your Location"
    except Exception as e:
        print(f"City Name Error: {e}")
        return "Your Location"

if __name__ == '__main__':
    app.run(debug=True, port=5000)