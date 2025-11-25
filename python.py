from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import pandas as pd

GROUP_NAME = "Iron Lady MC 25th Nov 2025"

# -------- SETUP CHROME PROPERLY (IMPORTANT) ---------
chrome_options = Options()
chrome_options.add_argument("--start-maximized")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=chrome_options
)

# -----------------------------------------------------

driver.get("https://web.whatsapp.com")
input("Scan QR Code in WhatsApp Web, then press ENTER here...")

time.sleep(4)

# Search for group
search_box = driver.find_element(By.XPATH, "//div[@title='Search input textbox']")
search_box.click()
time.sleep(1)
search_box.send_keys(GROUP_NAME)
time.sleep(3)

# Click group from search results
group = driver.find_element(By.XPATH, f"//span[@title='{GROUP_NAME}']")
group.click()
time.sleep(4)

# Open group info (latest WhatsApp Web UI)
header = driver.find_element(By.XPATH, "//header")
header.click()
time.sleep(3)

# Scroll participant list
scroll_panel = driver.find_element(By.XPATH, "//div[@role='region']")

for i in range(40):  # enough for 272 members
    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scroll_panel)
    time.sleep(0.4)

time.sleep(2)

# Extract participant numbers
elements = driver.find_elements(By.XPATH, "//span[contains(@class, '_ak8l')]")

members = []
for el in elements:
    text = el.text.strip()
    if text.startswith("+") and len(text) > 8:
        members.append(text)

# Remove duplicates
members = list(set(members))

# Save to Excel safely (to Desktop)
output_path = r"C:\Users\OM PRAKASH GADHWAL\Desktop\IronLadyMC_25Nov2025_contacts.xlsx"
df = pd.DataFrame({"Phone Numbers": members})
df.to_excel(output_path, index=False)

print("\nDONE! Excel File Saved To Desktop:")
print(output_path)
print(f"Total numbers extracted: {len(members)}")

driver.quit()
