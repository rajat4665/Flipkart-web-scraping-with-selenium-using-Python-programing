import os
from selenium import webdriver
from bs4 import BeautifulSoup
import time
import csv


class Flipkart():

    def __init__(self):

        # Here i get path of current workind directory
        self.current_path = os.getcwd()
        self.url = 'https://www.flipkart.com'
        # Chromedriver is just like a chrome. you can dowload latest by it website
        self.driver_path = os.path.join(os.getcwd(), 'chromedriver')
        self.driver = webdriver.Chrome(self.driver_path)

    def page_load(self):

        self.driver.get(self.url)
        try:
            login_pop = self.driver.find_element_by_class_name('_29YdH8')
            # Here .click function use to tap on desire elements of webpage
            login_pop.click()
            print('pop-up closed')
        except:
            pass
        # Here I get search field id from driver
        search_field = self.driver.find_element_by_class_name('LM6RPg')
        # Here .send_keys is use to input text in search field
        search_field.send_keys('smartphone' + '\n')
        # Here time.sleep is used to add delay for loading context in browser
        time.sleep(2)
        # Here we fetched driver page source from driver.
        page_html = self.driver.page_source
        # Here BeautifulSoup is dump page source into html format
        self.soup = BeautifulSoup(page_html, 'html.parser')

    def create_csv_file(self):

        # Here I created CSV file with desired header.
        rowHeaders = ["Name", "Storage_details", "Screen_size", "Camera_details", "Battery_details", "Processor", "Warranty", "Price in Rupees"]
        self.file_csv = open('Flipkart_output.csv', 'w', newline='', encoding='utf-8')
        self.mycsv = csv.DictWriter(self.file_csv, fieldnames=rowHeaders)
        # Writeheader is pre-defined function to write header
        self.mycsv.writeheader()

    def data_scrap(self):

        # Here I fetch all products div elements
        first_page_mobiles = (self.soup.find_all('div', class_='_3O0U0u'))
        for i in first_page_mobiles:
            Name = i.find('img', class_='_1Nyybr')['alt']
            price = i.find('div', class_='_1vC4OE _2rQ-NK')
            details = i.find_all("li")
            storage = details[0].text
            camera_details = details[2].text
            screen_size = details[1].text
            battery_details = details[3].text
            processor = details[4].text
            try:
                warranty_details = [j.text for j in details if j.text[:14] == "Brand Warranty"][0]
            except:
                warranty_details = "No data available"
            price = price.text[1:]
            self.mycsv.writerow({"Name": Name, "Storage_details": storage, "Screen_size": screen_size, "Camera_details": camera_details, "Battery_details": battery_details, "Processor": processor, "Warranty": warranty_details, "Price in Rupees": price})

    def tearDown(self):

        # Here driver.quit function is used to close chromedriver
        self.driver.quit()
        # Here we also need to close Csv file which I generated above
        self.file_csv.close()

if __name__ == "__main__":

    Flipkart = Flipkart()
    Flipkart.page_load()
    Flipkart.create_csv_file()
    Flipkart.data_scrap()
    Flipkart.tearDown()
    print("Task completed")
