import os, re
import time

import gspread
from google.cloud import vision

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from credentials import *

import smtplib, ssl, imghdr
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.message import EmailMessage

DEBUG = True
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'vision_key.json'

ALLERGENS = ['milk', 'egg', 'fish', 'soy', 'wheat', 'flour', 'nut', 'gluten', 'sesame', 'sulphite', 'lupin', 'celery', 'mustard', 'whey', 'cheese']
PRESERVATIVES = ['salt', 'sodium chloride', 'sucrose', 'acetic acid', 'ascorbic acid', 'benzoic acid', 'sodiium benzoate', 'sodium sulfite', 'sodium metabisulfite', 'potassium metabisulfite', 'sodium nitrate', 'sorbic nitrate', 'sorbic acid', 'tartaric acid', 'potassium benzoate', 'sodiium benzoate', 'citric acid']
CHEMICALS = ['sugar', 'msg', 'benzoyl peroxide', 'tbhq', 'high fructose corn syrup', 'monosodiium glutamate', 'artificial color', 'bha', 'bht', 'yellow 6', 'yellow 5', 'corn syrup', 'disodium inosinate', 'disodium guanylate']

def GetImageText(image_uri):
    try:
        vision_client = vision.ImageAnnotatorClient()
        image = vision.Image()

        image.source.image_uri = image_uri
        response = vision_client.text_detection(image=image)

        text = response.text_annotations[0].description
        return text
    except IndexError:
        print('Retrying Google Cloud OCR!')
        time.sleep(10)
        return getImageText(image_uri)

def CleanText(imageText):
    text = imageText.split('\n')
    for i in range(len(text)):
        try:
            line = text[i]
            if ('$' in line) or (len(line) <= 3):
                text.remove(line)
            else:
                text[i] = ' '.join(line.split()[:5])
        except IndexError:
            break
    return text

def GetItems(text):
    items = []
    for i in range(len(text)):
        line = text[i]
        if line == 'Qty:': items.append(text[i+1])
    return items

def FoodLookup(items):
    chrome_options = Options()
    chrome_options.binary_location = os.environ.get("GOOGLE_CHROME_BIN")
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--no-sandbox')
    if not DEBUG: chrome_options.add_argument('--headless')

    # For Local Testing:
    if DEBUG: driver = webdriver.Chrome(ChromeDriverManager().install(), options=chrome_options)

    url = 'https://www.fooducate.com/'
    driver.get(url)
    searchURLs = {}
    ingredientsDict = {}
    dangerDict = {}

    for item in items:
        if DEBUG: print(item)
        searchBox = driver.find_element_by_xpath('/html/body/div[1]/header/nav/div/form/div/input')
        searchBox.clear()
        searchBox.send_keys(item)
        submit = driver.find_element_by_xpath('/html/body/div[1]/header/nav/div/form/div/button')
        submit.click()
        time.sleep(2.5)
        #driver.save_screenshot(f"images\{item}.png")
        firstResult = driver.find_element_by_xpath('/html/body/div[1]/div[1]/div/div/div/div/div[2]/div/div/ul/li[1]')
        firstResult.click()
        time.sleep(3)
        searchURLs[item] = driver.current_url
        ingredients = driver.find_element_by_xpath('/html/body/div[1]/div[1]/div/div/div/div[3]/div[1]/div[5]/div[2]/p')
        ingredientsDict[item] = ingredients.text
        dangerDict[item] = {}

        ingredientsList = ingredients.text.lower().split(', ')
        dangerDict[item]['allergen'] = []
        dangerDict[item]['preservative'] = []
        dangerDict[item]['chemical'] = []

        for ingredient in ingredientsList:
            ingredient = ingredient.replace(' (preservative)', '')
            ingredient = ingredient.replace('and ', '')
            ingredient = ingredient.replace('and/or ', '')

            punc = f"!()[];:'\,<>./?@#^&*~"
            for ele in punc:
                if ele in ingredient: ingredient = ingredient.replace(ele, '')

            if ingredient in ALLERGENS: dangerDict[item]['allergen'].append(ingredient)
            elif ingredient in PRESERVATIVES: dangerDict[item]['preservative'].append(ingredient)
            elif ingredient in CHEMICALS: dangerDict[item]['chemical'].append(ingredient)
            else:
                parts = ingredient.split(' ')
                for part in parts:
                    if part in ALLERGENS: dangerDict[item]['allergen'].append(ingredient)
                    elif part in PRESERVATIVES: dangerDict[item]['preservative'].append(ingredient)
                    elif part in CHEMICALS: dangerDict[item]['chemical'].append(ingredient)

    driver.quit()
    return searchURLs, ingredientsDict, dangerDict

def sendEmail(receiver_email, items, searchURLs, ingredientsDict, dangerDict):
    receiver_address = receiver_email
    sender_address = dummy['email']
    password = dummy['pw']

    email_body = ''
    for item in items:
        email_body += f"""<h2><a href='{searchURLs[item]}'>{item}</a></h2>
        <p><strong>Ingredients:</strong> {ingredientsDict[item]}</p>
        <p><strong>Allergens:</strong> {dangerDict[item]['allergen']}</p>
        <p><strong>Preservatives:</strong> {dangerDict[item]['preservative']}</p>
        <p><strong>Other Chemicals:</strong> {dangerDict[item]['chemical']}</p>
        """

    email_body_html = open("email-body.html","w")
    email_body_html.write(email_body)

    email_header_html = open('email-header.html')
    email_body_html = open('email-body.html')
    email_footer_html = open('email-footer.html')
    email_body = email_header_html.read() + email_body_html.read() + email_footer_html.read()

    msg = MIMEText(email_body, 'html')
    msg['To'] = receiver_address
    msg['From'] = sender_address
    msg['Subject'] = f"Check what's in your groceries!"

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        context = ssl.create_default_context()
        server.starttls(context=context)
        server.login(sender_address, password)
        server.sendmail(sender_address, receiver_address, msg.as_string())
    except Exception as e:
        print(f'Error {e}')
    finally:
        if DEBUG: print('Closing the smtplib server...')
        server.quit()

#################################################

while True:
    gc = gspread.service_account(filename='vision_key.json')
    worksheet = gc.open("Is My Food Safe - TypeForm").sheet1
    row = len(worksheet.get_all_values())
    if (worksheet.cell(row, 5).value == ''):
        try:
            image_address = worksheet.cell(row, 1).value
            receiver_email = worksheet.cell(row, 2).value

            text = GetImageText(image_address)
            if DEBUG: print(text)

            text = CleanText(text)
            if DEBUG: print(text)

            items = GetItems(text)
            if DEBUG: print(items)

            searchURLs, ingredientsDict, dangerDict = FoodLookup(items)
            if DEBUG: print(searchURLs)
            if DEBUG: print(dangerDict)

            sendEmail(receiver_email, items, searchURLs, ingredientsDict, dangerDict)
            worksheet.update_cell(row, 5, 'YES')
        except Exception as e:
            #worksheet.update_cell(row, 5, 'ERROR')
            print(e)
    time.sleep(20)
