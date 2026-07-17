import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
import time
from PIL import Image
import os

# --- CONFIG ---
app_full_name = "Medical Air Systems Application (MASA)"
st.set_page_config(page_title=app_full_name, layout="wide", page_icon="🚁")

# --- 1. DATA LOADING FUNCTIONS ---
@st.cache_data
def load_data():
    hubs = pd.read_csv('data/unified_drone_network.csv')
    facilities = pd.read_csv('data/df_health_diagnostic.csv')
    return hubs, facilities

# Function to locate the logo file
def get_logo():
    for ext in ['LOGO_MASA_FINAL.png', 'LOGO_MASA_FINAL.jpg']:
        if os.path.exists(ext):
            return ext
    return None

# --- 2. SESSION STATE INITIALIZATION ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'page' not in st.session_state:
    st.session_state['page'] = 'dispatch'
if 'order_data' not in st.session_state:
    st.session_state['order_data'] = {}

# --- 3. LOGIN PAGE (RGPD COMPLIANCE SIMULATION) ---
if not st.session_state['logged_in']:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        logo = get_logo()
        if logo:
            st.image(logo, use_container_width=True)
        
        st.title(f"🔐 {app_full_name}")
        st.info("💡 Click below to skip authentication")
        
        if st.button("🚀 Access Dispatch System (Demo Mode)", use_container_width=True):
            st.session_state['logged_in'] = True
            st.rerun()
            
        st.markdown("---")
        st.subheader("Staff Authentication")
        st.text_input("User Email")
        st.text_input("Password", type="password")
        if st.button("Login"):
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
    
    # NETWORK LOGIC
    distances = df_hubs.apply(lambda row: geodesic(target_coords, (row['Latitude'], row['Longitude'])).km, axis=1)
    df_hubs['dist_to_target'] = distances
    reachable = df_hubs[df_hubs['dist_to_target'] <= df_hubs['Range_km']]

    col_map, col_info = st.columns([2, 1])

    with col_info:
        st.subheader("📋 Dispatch Summary")
        if not reachable.empty:
            best_hub = reachable.sort_values('dist_to_target').iloc[0]
            st.success(f"**Optimal Hub:** {best_hub['Hub_ID']}")
            st.write(f"**Network Operator:** {best_hub['Operator']}")
            
            # Duration: 1.5 min/km + 5 min prep time
            duration = int(best_hub['dist_to_target'] * 1.5) + 5
            st.metric("Flight Distance", f"{best_hub['dist_to_target']:.2f} km")
            st.metric("Estimated Arrival (ETA)", f"{duration} min")
            
            if confirm_button:
                if total_weight > 0:
                    st.session_state['order_data'] = {
                        'facility': selected_fac, 'hub': best_hub['Hub_ID'],
                        'operator': best_hub['Operator'], 'duration': duration,
                        'drones': drones_needed, 'emergency': emergency
                    }
                    st.session_state['page'] = 'tracking'
                    st.rerun()
                else:
                    st.error("Error: Order is empty!")
        else:
            st.error("🚨 OUT OF RANGE: Target unreachable by current network.")

    with col_map:
        m = folium.Map(location=[target['Latitude'], target['Longitude']], zoom_start=8, tiles='CartoDB Positron')
        
        # DISPLAY NETWORK COVERAGE
        for _, hub in df_hubs.iterrows():
            color = 'purple' if hub['Operator'] == 'MASA' else 'black'
            # Hub Marker
            folium.Marker(
                [hub['Latitude'], hub['Longitude']], 
                icon=folium.Icon(color=color, icon='plane', prefix='fa'),
                tooltip=f"{hub['Hub_ID']} ({hub['Operator']})"
            ).add_to(m)
            # Coverage Circle
            folium.Circle(
                [hub['Latitude'], hub['Longitude']],
                radius=hub['Range_km'] * 1000,
                color=color,
                fill=True,
                fill_opacity=0.05,
                weight=1
            ).add_to(m)
        
        # Target Marker
        folium.Marker(target_coords, icon=folium.Icon(color='red', icon='hospital-o', prefix='fa')).add_to(m)
        
        # Flight Path Line
        if not reachable.empty:
            folium.PolyLine([target_coords, (best_hub['Latitude'], best_hub['Longitude'])], color="blue", weight=3, dash_array='10').add_to(m)
        
        st_folium(m, width="100%", height=550, key="dispatch_map")

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
        st.metric("Remaining Flight Time", f"{data['duration']} min")
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