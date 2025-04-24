import chainlit as cl
from config import initialize_earth_engine, setup_gemini
from Agents.farmbot_agent import create_farmbot_agent, get_random_farming_phrase
from services.analysis import FarmBotAnalyzer
from services.government import GovernmentSchemes
from services.weather import WeatherAPI
from utils.helpers import validate_coordinates
import random
from agents import Runner

# Initialize services
initialize_earth_engine()
run_config = setup_gemini()
farmbot = create_farmbot_agent()

@cl.on_chat_start
async def handle_chat_start():
    cl.user_session.set("history", [])
    welcome_msg = """Assalamu Alaikum! Mein FarmBot hoon, aap ka smart kheti sahayak. 💚

Aap mujh se pooch sakte hain:
- Fasal ka tajzia (coordinates de kar, maslan: 31.5204,74.3587)
- Mausam ka hal (current weather conditions)
- Sarkari schemeon ki maloomat (Kissan Package, etc.)
- Fasal ke liye mashwara (crop recommendations)
- Islamic tareeqon se kheti baari (Islamic farming methods)

Misaal ke taur par:
"31.5204,74.3587 par fasal ka tajzia karein"
"Mausam ka hal bataein Lahore ka"
"Kissan Package ke bare mein bataein"
"Gandum ke liye salah dein"

Aaiye, bataiye aapki kya madad karun?"""
    await cl.Message(content=welcome_msg).send()

@cl.on_message
async def handle_message(message: cl.Message):
    user_input = message.content
    history = cl.user_session.get("history", [])
    
    # Check for special requests first
    if any(word in user_input.lower() for word in ["scheme", "sarkari", "package", "پیکیج", "سرکاری"]):
        await handle_government_schemes(user_input)
        return
    
    if any(word in user_input.lower() for word in ["islamic", "islami", "اسلامی"]):
        await handle_islamic_farming_query(user_input)
        return
    
    if any(word in user_input.lower() for word in ["weather", "mausam", "موسم"]):
        await handle_weather_query(user_input)
        return
    
    # Parse user input
    parsed_input = FarmBotAnalyzer.parse_user_input(user_input)
    
    # Handle coordinate-based analysis
    if parsed_input.get("coordinates"):
        # Validate coordinates using the helper function
        lat, lon = parsed_input["coordinates"][0]
        if not validate_coordinates(lat, lon):
            response = "Maaf karein, ye coordinates Pakistan ke andar nahi hain. Sahi coordinates dijiye."
            if parsed_input["language"] == "urdu":
                response = "معذرت، یہ کوآرڈینیٹس پاکستان کے اندر نہیں ہیں۔ درست کوآرڈینیٹس دیں۔"
            await cl.Message(content=response).send()
            return
        
        # Show processing message
        processing_msg = await cl.Message(content="Aap ka hukum processing ho raha hai...").send()
        
        try:
            # Perform analysis based on parsed instructions
            analysis_data = FarmBotAnalyzer.get_analysis_data(
                coords=parsed_input["coordinates"],
                date_range=parsed_input.get("date_range"),
                analysis_type=parsed_input.get("analysis_type", "full"),
                other_instructions=parsed_input.get("other_instructions", [])
            )
            
            if not analysis_data or not isinstance(analysis_data, dict):
                await processing_msg.remove()
                error_msg = "Maaf karein, tajzia karne mein ghalti hui. Dobara koshish karein."
                if parsed_input["language"] == "urdu":
                    error_msg = "معذرت، تجزیہ کرتے وقت خرابی ہوئی۔ دوبارہ کوشش کریں۔"
                await cl.Message(content=error_msg).send()
                return
            
            # Generate PDF report
            report_file = FarmBotAnalyzer.generate_pdf_report(analysis_data, parsed_input)
            
            # Prepare response based on language preference
            point_data = analysis_data.get('point_0', {})
            if parsed_input["language"] == "urdu":
                response = f"""📍 Aap ka tajzia tayyar hai:\n\n"""
                
                if 'crop_type' in point_data:
                    response += f"Fasal ka qisam: {point_data['crop_type']}\n"
                if 'ndvi' in point_data:
                    ndvi = point_data['ndvi']
                    if isinstance(ndvi, (int, float)):
                        response += f"Sehat (NDVI): {ndvi:.2f}\n"
                    else:
                        response += f"Sehat (NDVI): {ndvi}\n"
                if 'soil_moisture' in point_data:
                    moisture = point_data['soil_moisture']
                    if isinstance(moisture, (int, float)):
                        response += f"Mattī kī namī (NDMI): {moisture:.2f}\n"
                if 'temperature' in point_data:
                    temp = point_data['temperature']
                    if isinstance(temp, (int, float)):
                        response += f"Darja hararat: {temp:.1f}°C\n"
                if 'pest_risk' in point_data:
                    response += f"Keeron ka khatra: {point_data['pest_risk']}\n"
                
                if 'weather' in point_data and point_data['weather']:
                    weather = point_data['weather']
                    response += f"\nMausam ka hal:\n"
                    response += f"Darja hararat: {weather.get('temperature', 'N/A')}°C\n"
                    response += f"Namī: {weather.get('humidity', 'N/A')}%\n"
                    response += f"Bārish: {weather.get('rain', 0)}mm\n"
                
                if 'recommendations' in point_data and isinstance(point_data['recommendations'], list):
                    response += "\nSalah:\n" + "\n".join(
                        [rec for rec in point_data['recommendations'] if any(c.isalpha() for c in rec[:2])]
                    )
                
                response += "\n\nComplete report download karne ke liye neeche diye gye button par click karein 👇"
            else:
                response = f"""📍 Your analysis is ready:\n\n"""
                
                if 'crop_type' in point_data:
                    response += f"Crop Type: {point_data['crop_type']}\n"
                if 'ndvi' in point_data:
                    ndvi = point_data['ndvi']
                    if isinstance(ndvi, (int, float)):
                        response += f"Health (NDVI): {ndvi:.2f}\n"
                    else:
                        response += f"Health (NDVI): {ndvi}\n"
                if 'soil_moisture' in point_data:
                    moisture = point_data['soil_moisture']
                    if isinstance(moisture, (int, float)):
                        response += f"Soil Moisture (NDMI): {moisture:.2f}\n"
                if 'temperature' in point_data:
                    temp = point_data['temperature']
                    if isinstance(temp, (int, float)):
                        response += f"Temperature: {temp:.1f}°C\n"
                if 'pest_risk' in point_data:
                    response += f"Pest Risk: {point_data['pest_risk']}\n"
                
                if 'weather' in point_data and point_data['weather']:
                    weather = point_data['weather']
                    response += f"\nWeather Conditions:\n"
                    response += f"Temperature: {weather.get('temperature', 'N/A')}°C\n"
                    response += f"Humidity: {weather.get('humidity', 'N/A')}%\n"
                    response += f"Rain: {weather.get('rain', 0)}mm\n"
                
                if 'recommendations' in point_data and isinstance(point_data['recommendations'], list):
                    response += "\nRecommendations:\n" + "\n".join(
                        [rec for rec in point_data['recommendations'] if any(c.isalpha() for c in rec[:2])]
                    )
                
                response += "\n\nClick the button below to download complete report 👇"
            
            # Send response with PDF
            elements = [
                cl.File(name=report_file, path=report_file, display="inline"),
                cl.Text(content="Complete Report Download Karein" if parsed_input["language"] == "urdu" 
                        else "Download Complete Report")
            ]
            
            await processing_msg.remove()
            await cl.Message(content=response, elements=elements).send()
            
            # Add random farming phrase
            await cl.Message(content=get_random_farming_phrase()).send()
            return
            
        except Exception as e:
            await processing_msg.remove()
            error_msg = f"Maaf karein, tajzia mein ghalti hui: {str(e)}"
            if parsed_input["language"] == "urdu":
                error_msg = f"معذرت، تجزیہ کرتے وقت خرابی ہوئی: {str(e)}"
            await cl.Message(content=error_msg).send()
            return
    
    # Normal chat flow for non-coordinate queries
    history.append({"role": "user", "content": user_input})
    msg = cl.Message(content="")
    await msg.send()

    result_streaming = Runner.run_streamed(
        input=history,
        run_config=run_config,
        starting_agent=farmbot
    )

    async for event in result_streaming.stream_events():
        if event.type == "raw_response_event" and hasattr(event.data, 'delta'):
            token = event.data.delta
            await msg.stream_token(token)

    final_output = result_streaming.final_output
    msg.content = final_output
    history.append({"role": "assistant", "content": final_output})
    cl.user_session.set("history", history)
    await msg.update()
async def handle_government_schemes(user_input: str):
    """Handle government scheme queries"""
    parsed = FarmBotAnalyzer.parse_user_input(user_input)
    language = parsed["language"]
    
    # Check if asking for specific scheme
    scheme_name = None
    for name in GovernmentSchemes.SCHEMES.keys():
        if name.lower() in user_input.lower():
            scheme_name = name
            break
    
    scheme_info = GovernmentSchemes.get_scheme_info(scheme_name, language)
    
    if "error" in scheme_info:
        response = "Maaf karein, koi scheme nahi mili. Yeh schemes mojood hain: " if language == "urdu" else \
                  "Sorry, no scheme found. Available schemes are: "
        schemes_list = "\n".join([f"- {name}" for name in GovernmentSchemes.SCHEMES.keys()])
        await cl.Message(content=response + schemes_list).send()
        return
    
    if scheme_name:
        # Single scheme response
        if language == "urdu":
            response = f"""**{scheme_name}**
            
Tafseel: {scheme_info['description']}
Eligibility: {scheme_info['eligibility']}
Faide: {scheme_info['benefits']}

Ziyada maloomat ke liye apne local agriculture office se raabta karein."""
        else:
            response = f"""**{scheme_name}**
            
Description: {scheme_info['description']}
Eligibility: {scheme_info['eligibility']}
Benefits: {scheme_info['benefits']}

Contact your local agriculture office for more details."""
    else:
        # All schemes response
        if language == "urdu":
            response = "**Pakistani Sarkari Kheti Schemes**\n\n"
            for name, details in scheme_info.items():
                response += f"**{name}**\n"
                response += f"{details['description']}\n\n"
            response += "Kisi khas scheme ke bare mein maloomat ke liye scheme ka naam likhein."
        else:
            response = "**Pakistani Government Farming Schemes**\n\n"
            for name, details in scheme_info.items():
                response += f"**{name}**\n"
                response += f"{details['description']}\n\n"
            response += "Ask about any specific scheme for more details."
    
    await cl.Message(content=response).send()

async def handle_islamic_farming_query(user_input: str):
    """Provide information about Islamic farming practices"""
    parsed = FarmBotAnalyzer.parse_user_input(user_input)
    language = parsed["language"]
    
    tips = FarmBotAnalyzer.get_islamic_farming_tips()
    
    if language == "urdu":
        response = "**Islami Kheti Baari ke Tareeqe**\n\n"
        response += "\n".join([tip for tip in tips if any(c.isalpha() for c in tip[:2])])
        response += "\n\nZiyada maloomat ke liye apne local imam ya agriculture expert se raabta karein."
    else:
        response = "**Islamic Farming Methods**\n\n"
        response += "\n".join([tip for tip in tips if any(c.isalpha() for c in tip[:2])])
        response += "\n\nConsult your local imam or agriculture expert for more information."
    
    await cl.Message(content=response).send()

async def handle_weather_query(user_input: str):
    """Handle weather-related queries"""
    parsed = FarmBotAnalyzer.parse_user_input(user_input)
    language = parsed["language"]
    
    # Try to extract location from input
    location = None
    if parsed.get("coordinates"):
        location = parsed["coordinates"][0]  # Use first coordinate pair
    
    # Handle case where no location specified
    if not location:
        if language == "urdu":
            response = "Mausam ka hal janane ke liye, kisi specific jagah ke coordinates dijiye (masalan: 31.5204,74.3587) ya shahr ka naam likhein."
        else:
            response = "To check weather, please provide coordinates (e.g., 31.5204,74.3587) or city name."
        await cl.Message(content=response).send()
        return
    
    # Get weather data
    lat, lon = location
    weather_data = WeatherAPI.get_weather(lat, lon)
    
    if "error" in weather_data:
        error_msg = "Mausam ka data hasil karne mein ghalti hui. Baad mein koshish karein." if language == "urdu" else \
                   "Error getting weather data. Please try again later."
        await cl.Message(content=error_msg).send()
        return
    
    # Prepare response
    if language == "urdu":
        response = f"""📍 Mausam ka hal ({weather_data['timestamp']})
        
Darja hararat: {weather_data['temperature']}°C
Namī: {weather_data['humidity']}%
Hawa ki raftar: {weather_data['wind_speed']} km/h
Halat: {weather_data['conditions'].capitalize()}
Bārish (pichle 1 ghante mein): {weather_data['rain']}mm

Allah aap ki fasal ko har bura asar se bachaye 🤲"""
    else:
        response = f"""📍 Weather Conditions ({weather_data['timestamp']})
        
Temperature: {weather_data['temperature']}°C
Humidity: {weather_data['humidity']}%
Wind Speed: {weather_data['wind_speed']} km/h
Conditions: {weather_data['conditions'].capitalize()}
Rain (last 1 hour): {weather_data['rain']}mm

May Allah protect your crops from any harm 🤲"""
    
    await cl.Message(content=response).send()