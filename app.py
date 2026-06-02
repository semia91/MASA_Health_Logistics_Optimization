import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import os

# --- CONFIG ---
app_full_name = "Medical Air Systems Application (MASA)"
st.set_page_config(page_title=app_full_name, layout="wide", page_icon="🚁")

# URL de ton API FastAPI MLOps locale (Container Docker port 8000 via ngrok)
API_MLOPS_URL = "https://gesture-valid-gigabyte.ngrok-free" 

# --- 1. DATA LOADING FUNCTIONS ---
@st.cache_data
def load_data():
    # Chargement des hôpitaux dans le sous-dossier data
    facilities = pd.read_csv('data/df_health_diagnostic.csv')
    # Réintégration du fichier des hubs pour l'affichage visuel de la carte
    hubs = pd.read_csv('data/unified_drone_network.csv')
    return hubs, facilities

def get_logo():
    for ext in ['LOGO_MASA_FINAL.png', 'LOGO_MASA_FINAL.jpg']:
        if os.path.exists(ext):
            return ext
    return None

def get_live_weather(lat, lon):
    """Va chercher la météo en direct au Ghana pour les coordonnées GPS"""
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()["current"]
            return data["wind_speed_10m"], data["temperature_2m"]
    except Exception:
        pass
    return 15.0, 30.0  # Valeurs de secours

# --- 2. SESSION STATE INITIALIZATION ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'page' not in st.session_state:
    st.session_state['page'] = 'dispatch'
if 'order_data' not in st.session_state:
    st.session_state['order_data'] = {}

# --- 3. LOGIN PAGE (CONFORMITÉ RGPD PRÉSERVÉE) ---
if not st.session_state['logged_in']:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        logo = get_logo()
        if logo:
            st.image(logo, use_container_width=True)
        
        st.title(f"🔐 {app_full_name}")
        st.info("💡 Click below to skip authentication (Demo Mode)")
        
        if st.button("🚀 Access Dispatch System (Demo Mode)", use_container_width=True):
            st.session_state['logged_in'] = True
            st.rerun()
            
        st.markdown("---")
        st.subheader("Staff Authentication (RGPD Compliant Workspace)")
        st.text_input("User Email (Logs encrypted)")
        st.text_input("Password", type="password")
        if st.button("Login Secured"):
            st.session_state['logged_in'] = True
            st.rerun()
    st.stop()

# --- 4. LOAD ASSETS ---
df_hubs, df_facilities = load_data()

# ---------------------------------------------------------
# PAGE 1: DISPATCH CENTER
# ---------------------------------------------------------
if st.session_state['page'] == 'dispatch':
    
    # SIDEBAR
    st.sidebar.title("MASA Control")
    logo = get_logo()
    if logo:
        st.sidebar.image(logo, use_container_width=True)

    st.sidebar.subheader("📍 1. Destination")
    selected_fac = st.sidebar.selectbox("Select Health Facility:", df_facilities['Facility_Name'].unique())
    target = df_facilities[df_facilities['Facility_Name'] == selected_fac].iloc[0]
    target_coords = (target['Latitude'], target['Longitude'])

    # Extraction de la météo live
    live_wind, live_temp = get_live_weather(target['Latitude'], target['Longitude'])

    st.sidebar.subheader("📦 2. Mixed Order")
    emergency = st.sidebar.select_slider("Urgency Level:", options=["Routine", "Urgent", "Critical"])
    col_v, col_b, col_m = st.sidebar.columns(3)
    qty_v = col_v.number_input("Vaccines", min_value=0, step=1)
    qty_b = col_b.number_input("Blood", min_value=0, step=1)
    qty_m = col_m.number_input("Meds", min_value=0, step=1)

    total_weight = (qty_v * 0.2) + (qty_b * 0.5) + (qty_m * 0.3)
    drones_needed = int(-(total_weight // -2.0)) if total_weight > 0 else 0
    st.sidebar.info(f"Payload: {total_weight:.2f} kg | Drones: {drones_needed}")
    
    confirm_button = st.sidebar.button("✅ Confirm Order", use_container_width=True)

    st.title(f"🛰️ {app_full_name}")
    
    col_map, col_info = st.columns([1, 1])

    with col_info:
        st.subheader("📋 MLOps Real-Time Dispatch Summary")
        st.write(f"🌤️ **Live Weather at Destination:** {live_wind} km/h wind | {live_temp}°C")
        
        # Requête vers ton API FastAPI
        payload = {
            "hospital_latitude": float(target['Latitude']),
            "hospital_longitude": float(target['Longitude']),
            "weight_kg": float(total_weight),
            "wind_speed_kmh": float(live_wind),
            "air_temperature_c": float(live_temp)
        }
        
        assigned_hub_data = None
        try:
            response = requests.post(API_MLOPS_URL, json=payload, timeout=5)
            if response.status_code == 200:
                assigned_hub_data = response.json()
                
                st.success(f"**Assigned Hub:** {assigned_hub_data['assigned_hub_id']}")
                st.write(f"**Network Operator:** {assigned_hub_data['hub_operator']}")
                
                c_dist, c_eta, c_bat = st.columns(3)
                c_dist.metric("Calculated Distance", f"{assigned_hub_data['distance_km']} km")
                c_eta.metric("ML Predicted ETA", f"{assigned_hub_data['predicted_eta_minutes']} min")
                c_bat.metric("Predicted Battery Loss", f"{assigned_hub_data['predicted_battery_loss_pct']} %")
                
                if confirm_button:
                    if total_weight > 0:
                        st.session_state['order_data'] = {
                            'facility': selected_fac, 'hub': assigned_hub_data['assigned_hub_id'],
                            'operator': assigned_hub_data['hub_operator'], 'duration': assigned_hub_data['predicted_eta_minutes'],
                            'battery_loss': assigned_hub_data['predicted_battery_loss_pct'],
                            'drones': drones_needed, 'emergency': emergency
                        }
                        st.session_state['page'] = 'tracking'
                        st.rerun()
                    else:
                        st.error("Error: Order is empty!")
            else:
                st.error("🚨 Backend Server Error (500). Impossible de récupérer les prédictions.")
        except Exception:
            st.warning("🔌 En attente de connexion avec le conteneur MLOps local (Vérifie uvicorn/ngrok).")

    with col_map:
        m = folium.Map(location=[target['Latitude'], target['Longitude']], zoom_start=7, tiles='CartoDB Positron')
        
        # RENDU VISUEL DES HUBS SUR LA CARTE
        for _, hub in df_hubs.iterrows():
            color = 'purple' if hub['Operator'] == 'MASA' else 'black'
            folium.Marker(
                [hub['Latitude'], hub['Longitude']], 
                icon=folium.Icon(color=color, icon='plane', prefix='fa'),
                tooltip=f"{hub['Hub_ID']} ({hub['Operator']})"
            ).add_to(m)
            
            folium.Circle(
                [hub['Latitude'], hub['Longitude']],
                radius=hub['Range_km'] * 1000,
                color=color,
                fill=True,
                fill_opacity=0.03,
                weight=1
            ).add_to(m)
        
        # Marqueur de l'hôpital cible
        folium.Marker(target_coords, icon=folium.Icon(color='red', icon='hospital-o', prefix='fa')).add_to(m)
        
        # Dessiner le tracé dynamique entre l'hôpital et le Hub sélectionné par l'API
        if assigned_hub_data:
            matched_hub = df_hubs[df_hubs['Hub_ID'] == assigned_hub_data['assigned_hub_id']]
            if not matched_hub.empty:
                hub_row = matched_hub.iloc[0]
                folium.PolyLine(
                    [target_coords, (hub_row['Latitude'], hub_row['Longitude'])], 
                    color="blue", weight=3, dash_array='10',
                    tooltip="Active Flight Path"
                ).add_to(m)
        
        st_folium(m, width="100%", height=500, key="dispatch_map")

# ---------------------------------------------------------
# PAGE 2: LIVE TRACKING
# ---------------------------------------------------------
elif st.session_state['page'] == 'tracking':
    data = st.session_state['order_data']
    st.title("📦 Real-Time Mission Tracking")
    st.success(f"Order successfully dispatched to **{data['facility']}**")
    
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🔍 Mission Details")
        st.write(f"**Origin Hub:** {data['hub']} ({data['operator']})")
        st.write(f"**Priority:** {data['emergency']}")
        st.write(f"**Fleet:** {data['drones']} drones deployed")
        st.metric("Model Predicted Flight Time", f"{data['duration']} min")
        st.metric("Estimated Battery Consumption", f"{data['battery_loss']} %")
    with c2:
        st.subheader("📈 Flight Progress")
        tracking_table = {
            "Milestone": ["Order Received", "Drone Arming", "Take-off", "En Route", "Delivery"], 
            "Status": ["✅ Completed", "✅ Completed", "🚀 In Progress", "⏳ Pending", "⏳ Pending"]
        }
        st.table(pd.DataFrame(tracking_table))

    st.markdown("---")
    if st.button("➕ Start New Mission"):
        st.session_state['page'] = 'dispatch'
        st.rerun()

# LOGOUT
st.sidebar.markdown("---")
if st.sidebar.button("Logout"):
    st.session_state['logged_in'] = False
    st.session_state['page'] = 'dispatch'
    st.rerun()
