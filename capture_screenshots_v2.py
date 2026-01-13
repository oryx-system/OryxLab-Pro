import asyncio
from playwright.async_api import async_playwright
import os
from datetime import datetime, timedelta

async def run():
    async with async_playwright() as p:
        # iPhone 13 Pro dimensions
        iphone_13 = p.devices['iPhone 13 Pro']
        browser = await p.chromium.launch(headless=True)
        # Grant microphone/camera permissions if needed (not needed for this app but good practice)
        context = await browser.new_context(**iphone_13, permissions=[])
        
        output_dir = os.path.join(os.getcwd(), 'screenshots_v2')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        page = await context.new_page()

        # 1. Main Page
        print("1. Capturing Main Page...")
        await page.goto("http://127.0.0.1:5000/")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=os.path.join(output_dir, "1_Main.png"))

        # 2. Reservation Step 1: Open Calendar Modal
        # Assuming there is a FullCalendar interaction. We need to click a date.
        # This part might be tricky if the DOM structure is complex.
        # Let's try to click a 'td' with 'fc-daygrid-day' class.
        print("2. Capturing Reservation Modal...")
        today = datetime.now().strftime('%Y-%m-%d')
        # Wait for calendar to load
        try:
            await page.wait_for_selector('.fc-daygrid-day', timeout=5000)
            # Click on today or tomorrow
            await page.click(f'.fc-daygrid-day[data-date="{today}"]')
            await page.wait_for_timeout(1000) # Wait for modal animation
            await page.screenshot(path=os.path.join(output_dir, "2_Reservation_Modal.png"))
        except:
             print("Could not click calendar day. Skipping modal screenshot.")

        # 3. Reservation Step 2: Fill Form
        print("3. Filling Reservation Form...")
        try:
            # Check if modal is visible
            await page.fill('#resName', '김지혜')
            await page.fill('#resPhone', '010-1234-5678')
            await page.fill('#resPassword', '1234')
            await page.fill('#resPurpose', '독서 및 개인 공부')
            
            # Select time (start/end) if they are inputs
            # Assuming simple inputs for now based on app.py logic roughly
            # The modal logic usually auto-fills date, user picks time.
            # We will just screenshot the "Filled" state.
            await page.screenshot(path=os.path.join(output_dir, "3_Reservation_Filled.png"))
        except:
             print("Could not fill form.")

        # 4. Reservation Step 3: Draw Signature
        print("4. Drawing Signature...")
        try:
            # Canvas selector assumption: '#signaturePad'
            canvas = await page.wait_for_selector('canvas', timeout=2000)
            if canvas:
                box = await canvas.bounding_box()
                # Draw a simple squiggle
                await page.mouse.move(box['x'] + 20, box['y'] + 50)
                await page.mouse.down()
                await page.mouse.move(box['x'] + 50, box['y'] + 50)
                await page.mouse.move(box['x'] + 50, box['y'] + 80)
                await page.mouse.move(box['x'] + 80, box['y'] + 20)
                await page.mouse.up()
                await page.wait_for_timeout(500)
                await page.screenshot(path=os.path.join(output_dir, "4_Reservation_Signature.png"))
        except Exception as e:
            print(f"Could not draw signature: {e}")

        # 5. Check-in Page
        print("5. Capturing Check-in Page...")
        await page.goto("http://127.0.0.1:5000/checkin")
        await page.wait_for_timeout(1000)
        # Use correct IDs from checkin.html: checkinPhone, checkinPw
        try:
            await page.wait_for_selector('#checkinPhone', state='visible', timeout=5000)
            await page.fill('#checkinPhone', '010-1234-5678')
            await page.fill('#checkinPw', '1234')
            await page.wait_for_timeout(500) # Wait for typing to finish visuals
            await page.screenshot(path=os.path.join(output_dir, "5_Checkin_Filled.png"))
        except Exception as e:
            print(f"Check-in capture failed: {e}")

        # 6. My Page
        print("6. Capturing My Page...")
        await page.goto("http://127.0.0.1:5000/my")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=os.path.join(output_dir, "6_MyPage.png"))
        
        # 7. Checkout (Simulation via Checkout Modal if accessible from MyPage or separate?)
        # Base app.py suggests `checkout_process`.
        # Usually it's a modal on MyPage. We might not be able to trigger it easily without a real checked-in reservation.
        # We will try to capture the "empty" MyPage for now, or if possible, simulate a logged-in state.
        
        await browser.close()
        print(f"Screenshots saved to {output_dir}")

if __name__ == "__main__":
    asyncio.run(run())
