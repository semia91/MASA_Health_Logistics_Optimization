# 📊 BUSINESS ANALYSIS REPORT
## Strategic Optimization of Drone Medical Logistics in Ghana

---

### 1. Financial Definitions & Project Scope
To ensure a clear understanding of the financial modeling used in the Python notebooks, we define the two primary cost pillars:

* **CAPEX (Capital Expenditure):** Initial investment required to establish the physical network. This includes hub infrastructure, hardware, and the initial drone fleet.
* **OPEX (Operating Expenditure):** Monthly recurring costs to maintain operations, including local staffing, power, maintenance, and telecommunications.

---

### 2. Baseline: The Standard Model (Zipline)
The current network in Ghana follows a centralized, heavy-infrastructure model.

| Item | Value | Source / Justification |
| :--- | :--- | :--- |
| **Standard Hub CAPEX** | **$2,000,000** | High-cost automated launch (catapult) and recovery systems. |
| **Monthly OPEX per Hub** | **$26,000** | Based on current Ministry of Health "take-or-pay" service agreements. |
| **Technical Radius** | **80 km** | Fixed-wing drone autonomy limits for safe round-trips. |

**Context:** As of 2025/2026, the Ghanaian government has accumulated ~$15M in arrears due to the high fixed costs of this model, leading to the suspension of 3 vital centers.

---

### 3. Proposed Strategy: The Hybrid Micro-Hub Model (MASA)
Our Scenario B focuses on decentralized "Last-Mile" delivery using VTOL (Vertical Take-Off and Landing) technology.

#### A. Micro-Hub CAPEX Breakdown ($50,100)
* **Modular Infrastructure:** $15,000 (Solar-powered container units).
* **Software & Ground Systems:** $10,000.
* **Initial Fleet (3 Drones):** $25,100 (Average unit price of $8,366).

#### B. Monthly OPEX Breakdown ($2,107)
* **Local Staffing:** $1,200 (Training local health workers as supervisors).
* **Maintenance & Spares:** $600.
* **Utilities & Connectivity:** $307.

---

### 4. Technical Specifications: Drone Fleet
The modeling utilizes a diversified fleet to balance payload and cost efficiency.

| Drone Type | Technology | Est. Price | Capacity |
| :--- | :--- | :--- | :--- |
| **Standard VTOL** | Hybrid | **$8,500** | High-frequency medical supply |
| **Light Multirotor** | Electric | **$5,000** | Emergency serum/vaccine |
| **Zipline Zip** | Fixed-Wing | **~$25,000** | Heavy regional transport |

---

### 5. Strategic ROI & Impact
By switching to a hybrid model optimized by the **MCLP (Maximal Covering Location Problem)** algorithm:

* **Financial Efficiency:** We achieve 98% coverage with a total expansion CAPEX of **$1.35M** (for 25 hubs), whereas reaching the same target with standard hubs would exceed **$10M**.
* **Operational Savings:** The average flight distance drops from **45km to 17.5km**, reducing the cost per delivery to an estimated **$4.80**.
* **Social Impact:** 5.4 million additional citizens are brought within a 20-minute delivery window.

---
**Sources:** *Ghana Ministry of Health Audit (2025), VillageReach Economic Evaluation (2024), LaunchBase Africa Market Analysis (2026).*
