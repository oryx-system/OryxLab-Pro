import asyncio
from playwright.async_api import async_playwright
import os

async def run():
    async with async_playwright() as p:
        # iPhone 13 Pro dimensions
        iphone_13 = p.devices['iPhone 13 Pro']
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(**iphone_13)
        
        # Ensure screenshot directory exists
        output_dir = os.path.join(os.getcwd(), 'screenshots')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        page = await context.new_page()

        # 1. Main Page
        print("Capturing Main Page...")
        await page.goto("http://127.0.0.1:5000/")
        await page.wait_for_timeout(1000) # Wait for animations
        await page.screenshot(path=os.path.join(output_dir, "1_main.png"))

        # 2. Check-in Page
        print("Capturing Check-in Page...")
        await page.goto("http://127.0.0.1:5000/checkin")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=os.path.join(output_dir, "2_checkin.png"))

        # 3. My Page (Initial View)
        print("Capturing My Page...")
        await page.goto("http://127.0.0.1:5000/my")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=os.path.join(output_dir, "3_mypage.png"))

        # 4. Login Page (for admin context in manual)
        print("Capturing Login Page...")
        await page.goto("http://127.0.0.1:5000/login")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=os.path.join(output_dir, "4_login.png"))

        await browser.close()
        print(f"Screenshots saved to {output_dir}")

if __name__ == "__main__":
    asyncio.run(run())
