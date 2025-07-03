from flask import Flask, request, jsonify, send_file
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import pandas as pd
import os
import uuid
import time
from threading import Thread
from webdriver_manager.chrome import ChromeDriverManager
import logging

app = Flask(__name__)

# Konfiguracija logging-a
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Konfiguracija sajtova i njihovih selektora cena
SITES = {
    'fonly.rs': {'selector': '.woocommerce-Price-amount.amount', 'url_template': 'https://fonly.rs/?s={}&post_type=product'},
    'shoppster.rs': {'selector': '.price-value', 'url_template': 'https://www.shoppster.rs/search?term={}'},
    'gigatron.rs': {'selector': '[itemprop="price"]', 'url_template': 'https://www.gigatron.rs/pretraga?trazi={}'},
    'tehnomanija.rs': {'selector': '.price', 'url_template': 'https://www.tehnomanija.rs/sr-rs/search?q={}'},
    'ananas.rs': {'selector': '.sc-1arj7wv-2.fXyDjU', 'url_template': 'https://www.ananas.rs/search?q={}'}
}

# Globalne promenljive za praćenje progress-a
scrape_progress = {'status': 'idle', 'progress': 0, 'total': 0, 'output_file': None}

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    driver_path = ChromeDriverManager().install()
    return webdriver.Chrome(executable_path=driver_path, options=chrome_options)

def scrape_price(driver, site, url_template, search_term, selector):
    try:
        url = url_template.format(search_term.replace(' ', '+'))
        driver.get(url)
        time.sleep(2)  # Čekanje da se stranica učita
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        price_element = soup.select_one(selector)
        if price_element:
            price = price_element.text.strip().replace('RSD', '').replace('din', '').replace(',', '').replace('.', '').strip()
            return float(price) if price.replace('.', '').isdigit() else None
        return None
    except Exception as e:
        logger.error(f"Greška prilikom scrapovanja {site}: {str(e)}")
        return None

def scrape_prices(devices):
    global scrape_progress
    driver = setup_driver()
    results = []
    
    scrape_progress['total'] = len(devices)
    scrape_progress['progress'] = 0
    scrape_progress['status'] = 'running'

    for device in devices:
        device_result = {'Uređaj': device}
        for site, config in SITES.items():
            price = scrape_price(driver, site, config['url_template'], device, config['selector'])
            device_result[site] = price if price else 'N/A'
        
        results.append(device_result)
        scrape_progress['progress'] += 1

    driver.quit()
    
    # Kreiranje izlaznog fajla
    output_file = f'output_{uuid.uuid4().hex}.xlsx'
    df = pd.DataFrame(results)
    df.to_excel(output_file, index=False)
    
    scrape_progress['status'] = 'completed'
    scrape_progress['output_file'] = output_file
    return output_file

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    global scrape_progress
    if 'file' not in request.files:
        return jsonify({'error': 'Nema fajla'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nije izabran fajl'}), 400
    
    if file and file.filename.endswith('.xlsx'):
        df = pd.read_excel(file)
        devices = df.iloc[:, 0].tolist()  # Pretpostavka da je prva kolona naziv uređaja
        
        # Resetovanje progress-a
        scrape_progress = {'status': 'running', 'progress': 0, 'total': len(devices), 'output_file': None}
        
        # Pokretanje scraping-a u posebnom thread-u
        Thread(target=scrape_prices, args=(devices,)).start()
        return jsonify({'message': 'Scraping započet'})
    
    return jsonify({'error': 'Fajl mora biti .xlsx'}), 400

@app.route('/progress')
def get_progress():
    return jsonify(scrape_progress)

@app.route('/download')
def download_file():
    if scrape_progress['status'] == 'completed' and scrape_progress['output_file']:
        return send_file(scrape_progress['output_file'], as_attachment=True)
    return jsonify({'error': 'Fajl nije spreman'}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))