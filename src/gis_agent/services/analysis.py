import ee
import re
import datetime
from typing import List, Tuple, Dict, Optional
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import A4
import tempfile
import os
import matplotlib.pyplot as plt
import numpy as np
from services.weather import WeatherAPI
from services.government import GovernmentSchemes
from utils.helpers import validate_coordinates, format_weather_data

class FarmBotAnalyzer:
    """Main analysis class for FarmBot with all agricultural analysis capabilities"""
    
    @staticmethod
    def parse_user_input(user_input: Optional[str]) -> Dict:
        """Parse user input to extract coordinates, date range, and analysis type with proper null checks"""
        # Initialize default result
        result = {
            "coordinates": None,
            "date_range": None,
            "analysis_type": "full",
            "language": "english",
            "other_instructions": [],
            "special_requests": []
        }

        # Handle null/empty input
        if not user_input or not isinstance(user_input, str):
            return result

        # Ensure string processing
        user_input = user_input.strip()
        if not user_input:
            return result

        # Language detection
        if any(word in user_input.lower() for word in ["urdu", "اردو"]):
            result["language"] = "urdu"
            
        # Coordinate parsing with try-except
        coord_pattern = r'(\d+\.\d+)\s*,\s*(\d+\.\d+)'
        try:
            coords = re.findall(coord_pattern, user_input)
            if coords:
                result["coordinates"] = [(float(lat), float(lon)) for lat, lon in coords]
        except (ValueError, TypeError):
            pass
                    
        # Date range parsing with validation
        date_pattern = r'(?:from|between)\s*(\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+)\s*(?:to|and)\s*(\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+)'
        dates = re.search(date_pattern, user_input, re.IGNORECASE)
        if dates:
            try:
                start_date = FarmBotAnalyzer._parse_date_string(dates.group(1))
                end_date = FarmBotAnalyzer._parse_date_string(dates.group(2))
                if start_date and end_date:
                    result["date_range"] = (start_date, end_date)
            except (ValueError, AttributeError):
                pass
                    
        # Analysis type detection with fallback
        analysis_types = {
            "ndvi": "ndvi_only",
            "soil": "soil_moisture",
            "temperature": "temp_only",
            "health": "crop_health",
            "pest": "pest_risk"
        }
        
        try:
            for term, code in analysis_types.items():
                if term in user_input.lower():
                    result["analysis_type"] = code
                    break
        except AttributeError:
            pass  # Maintain default if string operations fail
                    
        return result
        
    @staticmethod
    def _parse_date_string(date_str: str) -> Optional[str]:
        """Helper to parse date strings with enhanced validation"""
        if not date_str or not isinstance(date_str, str):
            return None
            
        try:
            # Handle month-day formats (e.g., "15 June")
            if not any(char.isdigit() for char in date_str[:4]):
                parsed = datetime.datetime.strptime(date_str, "%d %B")
                return parsed.replace(year=datetime.datetime.now().year).strftime("%Y-%m-%d")
            
            # Handle standard YYYY-MM-DD format
            return datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return None
            
    @staticmethod
    def get_analysis_data(coords: List[Tuple[float, float]], 
                        date_range: Optional[Tuple[str, str]] = None,
                        analysis_type: str = "full",
                        other_instructions: List[str] = []) -> Dict:
        """Perform agricultural analysis on given coordinates"""
        if not coords:
            return {"error": "No coordinates provided"}
            
        if not date_range:
            end_date = datetime.datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
            date_range = (start_date, end_date)
            
        results = {}
        
        for i, (lat, lon) in enumerate(coords):
            if not validate_coordinates(lat, lon):
                results[f"point_{i}"] = {"error": "Coordinates outside Pakistan"}
                continue
                
            point = ee.Geometry.Point(lon, lat)
            aoi = point.buffer(1000)  # 1km buffer
            
            try:
                # Get weather data with enhanced error handling
                weather_data = {}
                try:
                    weather_data = WeatherAPI.get_weather(lat, lon)
                    if not isinstance(weather_data, dict):
                        weather_data = {}
                except Exception as e:
                    weather_data = {"error": f"Weather API error: {str(e)}"}
                
                # Get satellite data
                s2_collection = ee.ImageCollection('COPERNICUS/S2_HARMONIZED') \
                    .filterBounds(aoi) \
                    .filterDate(date_range[0], date_range[1]) \
                    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
                    
                s2_composite = s2_collection.median()
                
                # Initialize result structure with safe weather data formatting
                point_result = {
                    "coordinates": (lat, lon),
                    "analysis_period": f"{date_range[0]} to {date_range[1]}",
                    "weather": format_weather_data(weather_data) if isinstance(weather_data, dict) else {}
                }
            
            # [Rest of the analysis code remains the same...]
                # NDVI Analysis
                if analysis_type in ["full", "ndvi_only", "crop_health"]:
                    ndvi = s2_composite.normalizedDifference(['B8', 'B4']).rename('NDVI')
                    ndvi_value = ndvi.reduceRegion(
                        reducer=ee.Reducer.mean(),
                        geometry=aoi,
                        scale=10
                    ).get('NDVI').getInfo()
                    point_result["ndvi"] = ndvi_value
                    point_result["crop_health"] = FarmBotAnalyzer._assess_crop_health(ndvi_value)
                    
                # Soil Moisture Analysis
                if analysis_type in ["full", "soil_moisture"]:
                    ndmi = s2_composite.normalizedDifference(['B8', 'B11']).rename('NDMI')
                    ndmi_value = ndmi.reduceRegion(
                        reducer=ee.Reducer.mean(),
                        geometry=aoi,
                        scale=20
                    ).get('NDMI').getInfo()
                    point_result["soil_moisture"] = ndmi_value
                    
                results[f"point_{i}"] = point_result
                
            except Exception as e:
                results[f"point_{i}"] = {"error": str(e)}
                
        return results
        
    @staticmethod
    def _assess_crop_health(ndvi_value: float) -> str:
        """Assess crop health based on NDVI value"""
        if not isinstance(ndvi_value, (int, float)):
            return "Unknown"
            
        if ndvi_value > 0.7: return "Excellent"
        elif ndvi_value > 0.5: return "Good"
        elif ndvi_value > 0.3: return "Moderate"
        else: return "Poor"
        
    @staticmethod
    def generate_pdf_report(data: Dict, instructions: Dict = None) -> str:
        """Generate professional PDF report from analysis data with enhanced error handling"""
        if instructions is None:
            instructions = {}
        
        # Enhanced input validation
        if not data or not isinstance(data, dict):
            raise ValueError("Invalid data format - expected dictionary with analysis results")
        
        # Check if data contains any point data (even with errors)
        if not data:
            raise ValueError("Empty analysis data - no points to generate report for")
        
        # Check if we have any valid points (either successful analyses or errors)
        has_any_data = False
        has_valid_data = False
        error_messages = []
        
        for point_key, point_data in data.items():
            if not isinstance(point_data, dict):
                error_messages.append(f"Invalid data format for {point_key}")
                continue
            
            has_any_data = True
            
            if 'error' not in point_data:
                has_valid_data = True
        
        if not has_any_data:
            raise ValueError("No valid point data structure found in input")
        
        # Create PDF even if we only have error messages (but include them in report)
        filename = os.path.join(tempfile.gettempdir(), "farmbot_analysis_report.pdf")
        doc = SimpleDocTemplate(filename, pagesize=A4,
                            rightMargin=72, leftMargin=72,
                            topMargin=72, bottomMargin=72)
        
        styles = getSampleStyleSheet()
        
        # Custom styles
        styles['Title'].fontName = 'Helvetica-Bold'
        styles['Title'].fontSize = 18
        styles['Title'].leading = 22
        styles['Title'].alignment = 1
        styles['Title'].spaceAfter = 20
        
        if 'Heading1' not in styles:
            styles.add(ParagraphStyle(name='Heading1', 
                                fontSize=14, 
                                leading=18, 
                                spaceAfter=12,
                                fontName='Helvetica-Bold',
                                textColor=colors.HexColor('#2E7D32')))
        
        if 'Heading2' not in styles:
            styles.add(ParagraphStyle(name='Heading2', 
                                fontSize=12, 
                                leading=16, 
                                spaceAfter=8,
                                fontName='Helvetica-Bold',
                                textColor=colors.HexColor('#2E7D32')))
        
        if 'BodyText' not in styles:
            styles.add(ParagraphStyle(name='BodyText', 
                                fontSize=10, 
                                leading=14,
                                spaceAfter=6))
        
        if 'Footer' not in styles:
            styles.add(ParagraphStyle(name='Footer', 
                                fontSize=8, 
                                leading=10,
                                textColor=colors.grey))
        
        # Create elements for the PDF
        elements = []
        
        # Add cover page
        elements.append(Paragraph("FarmBot Analysis Report", styles['Title']))
        elements.append(Spacer(1, 0.5*inch))
        
        if not has_valid_data:
            warning_style = ParagraphStyle(
                name='Warning',
                parent=styles['BodyText'],
                textColor=colors.red,
                fontSize=12,
                leading=14
            )
            elements.append(Paragraph("WARNING: Limited Report Data Available", warning_style))
            elements.append(Spacer(1, 0.2*inch))
        
        elements.append(Paragraph(f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['BodyText']))
        elements.append(Spacer(1, 0.5*inch))
        
        # Add error summary page if there were errors
        if error_messages or not has_valid_data:
            elements.append(Paragraph("Analysis Issues Encountered", styles['Heading1']))
            elements.append(Spacer(1, 0.2*inch))
            
            if error_messages:
                for msg in error_messages:
                    elements.append(Paragraph(f"• {msg}", styles['BodyText']))
            else:
                for point_key, point_data in data.items():
                    if isinstance(point_data, dict) and 'error' in point_data:
                        loc = point_data.get('coordinates', 'Unknown location')
                        elements.append(Paragraph(
                            f"• {loc}: {point_data['error']}", 
                            styles['BodyText']
                        ))
            
            elements.append(Spacer(1, 0.3*inch))
            elements.append(Paragraph(
                "Note: Some analyses may be incomplete due to the above issues. "
                "Please verify your input parameters and try again.",
                styles['BodyText']
            ))
            elements.append(PageBreak())
        
        # Add analysis for each point
        for point_key, point_data in data.items():
            if not isinstance(point_data, dict) or 'error' in point_data:
                continue
                
            # Point header
            elements.append(Paragraph(f"Analysis for Location: {point_data.get('coordinates', 'Unknown')}", styles['Heading1']))
            elements.append(Spacer(1, 0.2*inch))
            
            # Analysis period
            elements.append(Paragraph(f"Analysis Period: {point_data.get('analysis_period', 'N/A')}", styles['BodyText']))
            elements.append(Spacer(1, 0.2*inch))
            
            # NDVI Analysis
            if 'ndvi' in point_data and isinstance(point_data['ndvi'], (int, float)):
                # Create NDVI chart
                fig, ax = plt.subplots(figsize=(6, 3))
                ndvi_value = point_data['ndvi']
                health_status = point_data.get('crop_health', 'Unknown')
                
                # Create NDVI scale visualization
                colors_ndvi = ['#d73027', '#fc8d59', '#fee08b', '#d9ef8b', '#91cf60', '#1a9850']
                positions = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
                
                for i in range(len(colors_ndvi)-1):
                    ax.fill_between([positions[i], positions[i+1]], 0, 1, 
                                  color=colors_ndvi[i], alpha=0.7)
                
                ax.plot([ndvi_value, ndvi_value], [0, 1], 'k-', lw=2)
                ax.text(ndvi_value+0.02, 0.5, f'{ndvi_value:.2f}\n({health_status})', 
                       va='center', fontsize=10)
                
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.set_xticks(positions)
                ax.set_xticklabels(['0.0', '0.2', '0.4', '0.6', '0.8', '1.0'])
                ax.set_yticks([])
                ax.set_title('NDVI Scale with Current Value', fontsize=10)
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['left'].set_visible(False)
                
                # Save the plot to a temporary file
                chart_path = os.path.join(tempfile.gettempdir(), f"ndvi_chart_{point_key}.png")
                plt.savefig(chart_path, dpi=300, bbox_inches='tight', transparent=True)
                plt.close()
                
                # Add chart to PDF
                elements.append(Paragraph("Crop Health Analysis (NDVI)", styles['Heading2']))
                elements.append(Spacer(1, 0.1*inch))
                elements.append(Image(chart_path, width=5*inch, height=2.5*inch))
                elements.append(Spacer(1, 0.2*inch))
                
                # NDVI interpretation
                ndvi_interpretation = {
                    'Excellent': 'Crops are very healthy with excellent growth',
                    'Good': 'Crops are healthy but could improve',
                    'Moderate': 'Crops show some issues needing attention',
                    'Poor': 'Crops are in poor condition, need immediate action'
                }.get(health_status, 'NDVI analysis not available')
                
                elements.append(Paragraph(f"<b>Interpretation:</b> {ndvi_interpretation}", styles['BodyText']))
                elements.append(Spacer(1, 0.3*inch))
            
            # Soil moisture analysis
            if 'soil_moisture' in point_data and isinstance(point_data['soil_moisture'], (int, float)):
                moisture_value = point_data['soil_moisture']
                elements.append(Paragraph("Soil Moisture Analysis", styles['Heading2']))
                elements.append(Spacer(1, 0.1*inch))
                
                # Create moisture meter
                fig, ax = plt.subplots(figsize=(6, 1))
                moisture_percent = min(max(moisture_value * 100, 0), 100)
                
                # Create gradient bar
                cmap = plt.get_cmap('YlGnBu')
                gradient = np.linspace(0, 1, 256).reshape(1, -1)
                ax.imshow(gradient, aspect='auto', cmap=cmap, extent=[0, 100, 0, 1])
                
                # Add indicator
                ax.plot([moisture_percent, moisture_percent], [0, 1], 'k-', lw=2)
                ax.text(moisture_percent+2, 0.5, f'{moisture_percent:.1f}%', 
                       va='center', fontsize=10)
                
                ax.set_xlim(0, 100)
                ax.set_ylim(0, 1)
                ax.set_yticks([])
                ax.set_xticks([0, 25, 50, 75, 100])
                ax.set_xticklabels(['Very Dry', 'Dry', 'Optimal', 'Wet', 'Very Wet'])
                ax.set_title('Soil Moisture Level', fontsize=10)
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['left'].set_visible(False)
                
                # Save the plot
                moisture_chart_path = os.path.join(tempfile.gettempdir(), f"moisture_chart_{point_key}.png")
                plt.savefig(moisture_chart_path, dpi=300, bbox_inches='tight', transparent=True)
                plt.close()
                
                elements.append(Image(moisture_chart_path, width=5*inch, height=1*inch))
                elements.append(Spacer(1, 0.1*inch))
                
                # Moisture recommendations
                if moisture_percent < 30:
                    rec = "Soil is too dry. Immediate irrigation needed."
                elif moisture_percent < 50:
                    rec = "Soil is somewhat dry. Consider irrigation soon."
                elif moisture_percent < 70:
                    rec = "Soil moisture is at optimal levels."
                else:
                    rec = "Soil is too wet. Reduce irrigation to prevent waterlogging."
                
                elements.append(Paragraph(f"<b>Recommendation:</b> {rec}", styles['BodyText']))
                elements.append(Spacer(1, 0.3*inch))
            
            # Weather data
            if 'weather' in point_data and point_data['weather']:
                weather = point_data['weather']
                elements.append(Paragraph("Weather Conditions", styles['Heading2']))
                elements.append(Spacer(1, 0.1*inch))
                
                weather_data = [
                    ["Parameter", "Value"],
                    ["Temperature", f"{weather.get('temperature', 'N/A')}°C"],
                    ["Humidity", f"{weather.get('humidity', 'N/A')}%"],
                    ["Wind Speed", f"{weather.get('wind_speed', 'N/A')} km/h"],
                    ["Conditions", weather.get('conditions', 'N/A').capitalize()],
                    ["Rainfall (last hour)", f"{weather.get('rain', 0)}mm"]
                ]
                
                weather_table = Table(weather_data, colWidths=[2*inch, 3*inch])
                weather_table.setStyle(TableStyle([
                    ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
                    ('FONTSIZE', (0,0), (-1,-1), 10),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#E3F2FD')),
                    ('GRID', (0,0), (-1,-1), 1, colors.lightgrey)
                ]))
                elements.append(weather_table)
                elements.append(Spacer(1, 0.3*inch))
                
                # Weather impact analysis
                temp = weather.get('temperature')
                if isinstance(temp, (int, float)):
                    if temp > 35:
                        impact = "High temperatures may stress crops. Provide shade and ensure adequate water."
                    elif temp < 10:
                        impact = "Low temperatures may damage crops. Consider protective measures."
                    else:
                        impact = "Temperatures are in optimal range for most crops."
                    
                    elements.append(Paragraph(f"<b>Weather Impact:</b> {impact}", styles['BodyText']))
                    elements.append(Spacer(1, 0.3*inch))
            
            # Recommendations section
            elements.append(Paragraph("Farm Management Recommendations", styles['Heading1']))
            elements.append(Spacer(1, 0.2*inch))
            
            # Generate recommendations based on analysis
            recommendations = []
            
            # NDVI-based recommendations
            if 'crop_health' in point_data:
                health = point_data['crop_health']
                if health == 'Poor':
                    recommendations.extend([
                        "✓ Apply fertilizer urgently",
                        "✓ Check for pests and diseases",
                        "✓ Test soil for nutrient deficiencies",
                        "✓ Increase irrigation if needed"
                    ])
                elif health == 'Moderate':
                    recommendations.extend([
                        "✓ Apply balanced fertilizer",
                        "✓ Monitor for early signs of pests",
                        "✓ Maintain proper irrigation",
                        "✓ Consider foliar feeding"
                    ])
                elif health == 'Good':
                    recommendations.extend([
                        "✓ Continue current practices",
                        "✓ Monitor crop health regularly",
                        "✓ Prepare for next growth stage"
                    ])
                else:  # Excellent
                    recommendations.extend([
                        "✓ Maintain excellent practices",
                        "✓ Document management strategies",
                        "✓ Explore intercropping options"
                    ])
            
            # Soil moisture recommendations
            if 'soil_moisture' in point_data and isinstance(point_data['soil_moisture'], (int, float)):
                moisture = point_data['soil_moisture']
                if moisture < 0.3:
                    recommendations.append("✓ Increase irrigation frequency immediately")
                elif moisture > 0.7:
                    recommendations.append("✓ Reduce irrigation to prevent waterlogging")
            
            # Weather-based recommendations
            if 'weather' in point_data:
                weather = point_data['weather']
                temp = weather.get('temperature')
                rain = weather.get('rain', 0)
                
                if isinstance(temp, (int, float)):
                    if temp > 35:
                        recommendations.append("✓ Use mulch or shade to reduce soil temperature")
                    if temp < 10:
                        recommendations.append("✓ Use protective covers for cold protection")
                
                if isinstance(rain, (int, float)) and rain > 10:
                    recommendations.append("✓ Ensure proper drainage to prevent waterlogging")
            
            # Add recommendations to PDF
            if recommendations:
                for rec in recommendations:
                    elements.append(Paragraph(f"• {rec}", styles['BodyText']))
            else:
                elements.append(Paragraph("No specific recommendations available based on current analysis.", styles['BodyText']))
            
            elements.append(Spacer(1, 0.3*inch))
            
            # Government schemes section
            elements.append(Paragraph("Applicable Government Schemes", styles['Heading2']))
            elements.append(Spacer(1, 0.1*inch))
            
            schemes = GovernmentSchemes.get_scheme_info(None, 'english')
            if schemes and isinstance(schemes, list):
                for scheme in schemes[:3]:  # Show top 3 relevant schemes
                    elements.append(Paragraph(f"<b>{scheme.get('name', 'N/A')}</b>", styles['BodyText']))
                    elements.append(Paragraph(scheme.get('description', 'No description available'), styles['BodyText']))
                    elements.append(Spacer(1, 0.1*inch))
            else:
                elements.append(Paragraph("Contact local agriculture office for scheme information.", styles['BodyText']))
            
            elements.append(Spacer(1, 0.5*inch))
            
            # Add page break if not last point
            if point_key != list(data.keys())[-1]:
                elements.append(PageBreak())
        
        # Add footer to each page
        def add_footer(canvas, doc):
            canvas.saveState()
            canvas.setFont('Helvetica', 8)
            status = "Partial" if not has_valid_data else "Complete"
            canvas.drawString(inch, 0.75*inch, 
                         f"FarmBot Analysis Report ({status}) • {datetime.datetime.now().strftime('%Y-%m-%d')} • Page {doc.page}")
            canvas.restoreState()
        
        # Build the PDF
        doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
        
        return filename