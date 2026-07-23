#!/usr/bin/env python3
"""
Gmail Account Creator Automation
Automates the initial form-filling steps of creating a Google/Gmail account using Playwright.
Pauses at the phone verification / security screen to allow manual completion before saving the credentials.
"""

import os
import csv
import time
import random
import string
from datetime import datetime
from playwright.sync_api import sync_playwright

# Sample pool of names for generating random accounts
FIRST_NAMES = ["Ahmad", "Sami", "Karim", "Tarek", "Fadi", "Rami", "Ziad", "Youssef", "Omar", "Hassan", "Nour", "Layla", "Sarah", "Reem", "Mona"]
LAST_NAMES = ["Haddad", "Masri", "Najjar", "Hariri", "Fadel", "Dagher", "Khoury", "Sayegh", "Saliba", "Ghanem", "Alami", "Jaber", "Zayn", "Assaf"]

# Realistic User Agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

def generate_password(length=12):
    """Generates a secure random password."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(random.choice(chars) for _ in range(length))

def generate_username(first, last):
    """Generates a random username candidate."""
    rand_num = random.randint(1000, 99999)
    # lowercase, remove spaces/special characters
    username = f"{first.lower()}{last.lower()}{rand_num}"
    return username

def log_created_account(email, password):
    """Saves the created credentials to a local CSV file."""
    csv_file = "created_accounts.csv"
    file_exists = os.path.isfile(csv_file)
    
    with open(csv_file, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Email", "Password", "CreationDate"])
        writer.writerow([email, password, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    print(f"\n[+] Account credentials saved to {csv_file}")

def run_creator():
    # Pick random details
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    username = generate_username(first_name, last_name)
    password = generate_password(14)
    email = f"{username}@gmail.com"
    
    print("\n" + "="*50)
    print("[*] Generating Gmail Account with details:")
    print(f"    Name: {first_name} {last_name}")
    print(f"    Email: {email}")
    print(f"    Password: {password}")
    print("="*50 + "\n")

    with sync_playwright() as p:
        # Launch headed browser so the user can interact
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox"
            ]
        )
        
        # Create a new context with a clean state
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York"
        )
        
        # Add stealth script to prevent navigator.webdriver detection
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = context.new_page()
        
        print("[*] Navigating to Google Sign-Up page...")
        # Direct URL to the sign up form
        page.goto("https://accounts.google.com/signup/v2/webcreateaccount?flowName=GlifWebSignIn&flowEntry=SignUp", wait_until="domcontentloaded")
        
        try:
            # Page 1: First Name & Last Name
            print("[*] Filling in name details...")
            page.wait_for_selector("input[name='firstName']", timeout=10000)
            page.fill("input[name='firstName']", first_name)
            page.fill("input[name='lastName']", last_name)
            
            # Click next
            next_btn = page.locator("button:has-text('Next'), span:has-text('Next'), button:has-text('التالي'), span:has-text('التالي')").first
            next_btn.click()
            time.sleep(2)
            
            # Page 2: Basic Information (DOB & Gender)
            print("[*] Filling in date of birth and gender...")
            # Wait for any of the fields on page 2
            page.wait_for_selector("input[name='day']", timeout=10000)
            
            # Random birth date
            day = str(random.randint(1, 28))
            year = str(random.randint(1985, 2003))
            
            page.fill("input[name='day']", day)
            page.fill("input[name='year']", year)
            
            # Select month (select element or dropdown)
            month_select = page.locator("select#month, select[name='month']")
            if month_select.count() > 0:
                month_select.select_option(index=random.randint(1, 12))
            else:
                # Sometimes it's a div list instead of normal select, try clicking it
                month_combobox = page.locator("div[aria-label='Month'], div#month").first
                month_combobox.click()
                time.sleep(1)
                page.locator("li[role='option']").nth(random.randint(0, 11)).click()
                
            # Select gender
            gender_select = page.locator("select#gender, select[name='gender']")
            if gender_select.count() > 0:
                # 1: Female, 2: Male, 3: Rather not say, 4: Custom
                gender_select.select_option(value="3") 
            else:
                # Div style gender dropdown
                gender_combobox = page.locator("div[aria-label='Gender'], div#gender").first
                gender_combobox.click()
                time.sleep(1)
                page.locator("li[role='option']").nth(2).click() # rather not say
                
            next_btn.click()
            time.sleep(2)
            
            # Page 3: Choose Username/Gmail
            print("[*] Configuring username...")
            # Wait for username input or option radio buttons
            page.wait_for_selector("input[name='Username'], input#username", timeout=10000)
            
            # Check if there is an input field for custom username
            username_input = page.locator("input[name='Username'], input#username")
            if username_input.is_visible():
                username_input.fill(username)
            else:
                # Sometimes it offers recommendations and we need to choose "Create your own Gmail address"
                create_own_opt = page.locator("li:has-text('Create your own Gmail address'), li:has-text('إنشاء عنوان Gmail خاص بك')").first
                if create_own_opt.is_visible():
                    create_own_opt.click()
                    time.sleep(1)
                    page.locator("input[name='Username'], input#username").fill(username)
                else:
                    # Just pick one of the recommended option radios
                    page.locator("input[type='radio']").first.click()
            
            next_btn.click()
            time.sleep(2)
            
            # Page 4: Set Password
            print("[*] Setting secure password...")
            page.wait_for_selector("input[name='Passwd']", timeout=10000)
            page.fill("input[name='Passwd']", password)
            page.fill("input[name='PasswdAgain']", password)
            
            next_btn.click()
            time.sleep(3)
            
        except Exception as e:
            print(f"[-] Automation encountered an issue or layout changed: {e}")
            print("[*] Continuing to manual mode so you can adjust manually...")

        # Step 5: Manual intervention for Phone Verification / CAPTCHA
        print("\n" + "!"*60)
        print("[!] PAUSED FOR MANUAL PHONE VERIFICATION & FINALIZATION [!]")
        print("    1. Look at the open browser window.")
        print("    2. Complete the phone verification (SMS code).")
        print("    3. Complete any additional steps (Recovery email, Terms of Service).")
        print("    4. Once the Gmail/Google Inbox fully loads and the account is created:")
        print("       -> Return here and press ENTER to save details and close the browser.")
        print("!"*60 + "\n")
        
        input("Press [ENTER] after the account has been fully created to log it... ")
        
        # Log credentials
        log_created_account(email, password)
        
        print("[*] Closing browser. Done!")
        browser.close()

if __name__ == "__main__":
    run_creator()
