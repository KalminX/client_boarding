import os
import sys
import time
import subprocess
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from contracts.models import Contract, ContractStatus
from clients.models import Client
from onboarding.models import OnboardingCase
from decimal import Decimal
from playwright.sync_api import sync_playwright

CURSOR_INJECTION_SCRIPT = """
(() => {
    function setupCursor() {
        if (document.getElementById('custom-playwright-cursor')) return;
        const cursor = document.createElement('div');
        cursor.id = 'custom-playwright-cursor';
        cursor.style.position = 'fixed';
        cursor.style.width = '24px';
        cursor.style.height = '24px';
        cursor.style.borderRadius = '50%';
        cursor.style.backgroundColor = 'rgba(239, 68, 68, 0.9)';
        cursor.style.border = '2.5px solid white';
        cursor.style.boxShadow = '0 0 12px rgba(0,0,0,0.6)';
        cursor.style.pointerEvents = 'none';
        cursor.style.zIndex = '9999999';
        cursor.style.transition = 'transform 0.04s ease';
        cursor.style.transform = 'translate(-50%, -50%)';
        cursor.style.top = '0px';
        cursor.style.left = '0px';
        document.body.appendChild(cursor);

        window.addEventListener('mousemove', (e) => {
            cursor.style.left = `${e.clientX}px`;
            cursor.style.top = `${e.clientY}px`;
        });

        window.addEventListener('mousedown', (e) => {
            cursor.style.transform = 'translate(-50%, -50%) scale(0.65)';
            cursor.style.backgroundColor = 'rgba(37, 99, 235, 0.95)';
            
            const ripple = document.createElement('div');
            ripple.style.position = 'fixed';
            ripple.style.left = `${e.clientX}px`;
            ripple.style.top = `${e.clientY}px`;
            ripple.style.width = '12px';
            ripple.style.height = '12px';
            ripple.style.borderRadius = '50%';
            ripple.style.backgroundColor = 'rgba(37, 99, 235, 0.6)';
            ripple.style.pointerEvents = 'none';
            ripple.style.zIndex = '9999998';
            ripple.style.transform = 'translate(-50%, -50%)';
            ripple.style.transition = 'all 0.35s ease-out';
            document.body.appendChild(ripple);
            
            setTimeout(() => {
                ripple.style.width = '50px';
                ripple.style.height = '50px';
                ripple.style.opacity = '0';
            }, 10);
            
            setTimeout(() => { ripple.remove(); }, 400);
        });

        window.addEventListener('mouseup', () => {
            cursor.style.transform = 'translate(-50%, -50%) scale(1)';
            cursor.style.backgroundColor = 'rgba(239, 68, 68, 0.9)';
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupCursor);
    } else {
        setupCursor();
    }
})();
"""

def smooth_move(page, start_x, start_y, end_x, end_y, steps=18, delay=0.015):
    for i in range(steps + 1):
        x = start_x + (end_x - start_x) * (i / steps)
        y = start_y + (end_y - start_y) * (i / steps)
        page.mouse.move(x, y)
        time.sleep(delay)

def move_and_click(page, selector, current_pos=[100, 100], click_delay=0.3):
    elem = page.wait_for_selector(selector, timeout=12000)
    elem.scroll_into_view_if_needed()
    time.sleep(0.15)
    box = elem.bounding_box()
    if box:
        target_x = max(10, min(1270, box['x'] + box['width'] / 2))
        target_y = max(10, min(710, box['y'] + box['height'] / 2))
        smooth_move(page, current_pos[0], current_pos[1], target_x, target_y)
        current_pos[0] = target_x
        current_pos[1] = target_y
        time.sleep(0.12)
        page.mouse.down()
        time.sleep(0.08)
        page.mouse.up()
        time.sleep(click_delay)
    else:
        elem.click()

def prepare_contract():
    client, _ = Client.objects.get_or_create(
        primary_email="demo.client@apexlogistics.com",
        defaults={
            "name": "Jordan Reed",
            "company_name": "Apex Global Logistics LLC",
            "billing_address": "200 South Michigan Ave, Suite 400, Chicago, IL 60604",
        }
    )
    contract, _ = Contract.objects.get_or_create(
        client=client,
        title="Master Logistics Software Agreement 2026",
        defaults={
            "contract_value": Decimal("35000.00"),
            "status": ContractStatus.SENT,
        }
    )
    contract.status = ContractStatus.SENT
    contract.signed_at = None
    contract.save()
    OnboardingCase.objects.filter(contract=contract).delete()
    return contract

def run_recording():
    output_dir = "recordings_raw"
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs("recordings", exist_ok=True)

    contract = prepare_contract()
    print(f"Prepared unsigned contract ID: {contract.id}")

    sample_doc_path = "sample_w9_tax_form.txt"
    with open(sample_doc_path, "w") as f:
        f.write("""FORM W-9 (Rev. March 2026) - Department of the Treasury Internal Revenue Service
1. Legal Entity Name: Apex Global Logistics LLC
2. Business Name: Apex Logistics
3. Federal Tax Classification: Limited Liability Company (Corporation)
4. Address: 200 South Michigan Ave, Suite 400, Chicago, IL 60604
Part I - Taxpayer Identification Number (TIN):
EIN: 36-9482103
Part II - Certification:
Under penalties of perjury, I certify that:
1. The number shown on this form is my correct taxpayer identification number.
2. I am not subject to backup withholding.
Authorized Signatory: Jordan Reed
Date: 2026-04-10
""")

    print("Launching Chromium in 1280x720 (720p) mode...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=output_dir,
            record_video_size={"width": 1280, "height": 720}
        )

        page = context.new_page()
        page.add_init_script(CURSOR_INJECTION_SCRIPT)
        
        pos = [640, 360]

        # 1. Login
        print("Step 1: Logging in as staff...")
        page.goto("http://127.0.0.1:8000/login/")
        page.wait_for_load_state("networkidle")
        time.sleep(0.8)

        move_and_click(page, "#id_username", pos)
        page.keyboard.type("admin", delay=50)
        time.sleep(0.2)

        move_and_click(page, "#id_password", pos)
        page.keyboard.type("admin123", delay=50)
        time.sleep(0.2)

        move_and_click(page, "button[type='submit']", pos, click_delay=1.5)
        page.wait_for_load_state("networkidle")

        # 2. Dashboard overview
        print("Step 2: Inspecting Dashboard metrics...")
        smooth_move(page, pos[0], pos[1], 350, 220)
        pos = [350, 220]
        time.sleep(1.2)

        # 3. Navigate to Contracts
        print("Step 3: Navigating to Contracts...")
        move_and_click(page, "a[href='/contracts/']", pos, click_delay=1.0)
        page.wait_for_load_state("networkidle")
        time.sleep(0.8)

        # Click the unsigned contract
        move_and_click(page, f"a[href='/contracts/{contract.id}/']", pos, click_delay=1.2)
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)

        # 4. Sign Contract & Trigger Onboarding
        print("Step 4: Signing Contract & Triggering Background Onboarding...")
        smooth_move(page, pos[0], pos[1], 800, 450)
        pos = [800, 450]
        time.sleep(0.6)
        
        move_and_click(page, "button:has-text('Sign Contract & Trigger Onboarding')", pos, click_delay=2.0)
        page.wait_for_load_state("networkidle")

        # Onboarding Case Workspace
        print("Step 5: Inside Onboarding Case Workspace...")
        time.sleep(2.0)

        # Extract Client Portal URL
        portal_url_elem = page.wait_for_selector("#portalUrlInput", timeout=8000)
        portal_url = portal_url_elem.input_value()
        print(f"Captured Portal URL: {portal_url}")

        # Highlight Integration Artifacts
        smooth_move(page, pos[0], pos[1], 500, 320)
        pos = [500, 320]
        time.sleep(1.5)

        # 5. Open Client Portal in a simulated second tab
        print("Step 6: Switching to Client Intake Portal...")
        client_page = context.new_page()
        client_page.add_init_script(CURSOR_INJECTION_SCRIPT)
        client_page.goto(portal_url)
        client_page.wait_for_load_state("networkidle")
        c_pos = [640, 360]
        time.sleep(1.2)

        # Fill Client Intake Form
        print("Step 7: Filling in Client Intake Questionnaire...")
        move_and_click(client_page, "#id_tax_id", c_pos)
        client_page.keyboard.type("36-9482103", delay=45)
        time.sleep(0.2)

        move_and_click(client_page, "#id_target_launch_date", c_pos)
        client_page.keyboard.type("2026-05-01", delay=45)
        time.sleep(0.2)

        move_and_click(client_page, "#id_technical_contact_name", c_pos)
        client_page.keyboard.type("Alex Mercer", delay=45)
        time.sleep(0.2)

        move_and_click(client_page, "#id_technical_contact_email", c_pos)
        client_page.keyboard.type("alex@apexlogistics.com", delay=45)
        time.sleep(0.2)

        move_and_click(client_page, "#id_primary_use_case", c_pos)
        client_page.keyboard.type("Automated enterprise freight onboarding with live GPS telemetry integration.", delay=25)
        time.sleep(0.3)

        move_and_click(client_page, "#id_privacy_consent_given", c_pos, click_delay=0.4)

        move_and_click(client_page, "button:has-text('Save & Submit Intake Questionnaire')", c_pos, click_delay=1.8)
        client_page.wait_for_load_state("networkidle")
        time.sleep(1.2)

        # Upload W-9 Document in client portal
        print("Step 8: Uploading W-9 Compliance Document in portal...")
        file_input = client_page.wait_for_selector("#id_file")
        file_input.set_input_files(os.path.abspath(sample_doc_path))
        time.sleep(0.8)

        smooth_move(client_page, c_pos[0], c_pos[1], 800, 350)
        c_pos = [800, 350]
        time.sleep(0.4)
        client_page.locator("form[action*='/documents/upload/'] button[type='submit']").click()
        client_page.wait_for_load_state("networkidle")
        time.sleep(2.0)
        client_page.close()

        # 6. Return to Staff View
        print("Step 9: Returning to Staff Case Workspace...")
        page.bring_to_front()
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(2.0)

        # Switch to Documents tab
        move_and_click(page, "#documents-tab", pos, click_delay=1.5)
        time.sleep(1.5)

        # Click Review Document
        move_and_click(page, "a[href*='/documents/'][href*='/review/']", pos, click_delay=1.8)
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)

        # Approve Document
        print("Step 10: Staff Human Verification & Approval...")
        smooth_move(page, pos[0], pos[1], 400, 560)
        pos = [400, 560]
        time.sleep(0.8)
        move_and_click(page, "button:has-text('Submit Review Decision')", pos, click_delay=1.8)
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)

        # Finalize Onboarding
        print("Step 11: Finalizing Onboarding Case...")
        move_and_click(page, "button:has-text('Finalize Onboarding')", pos, click_delay=2.0)
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)

        # Inspect Jobs & Integrations
        print("Step 12: Visiting Background Job Monitor...")
        move_and_click(page, "a[href='/jobs/']", pos, click_delay=1.8)
        page.wait_for_load_state("networkidle")
        time.sleep(2.0)

        print("Step 13: Visiting External Integrations Activity...")
        move_and_click(page, "a[href='/integrations/']", pos, click_delay=1.8)
        page.wait_for_load_state("networkidle")
        time.sleep(2.5)

        context.close()
        browser.close()

    print("Encoding video with ffmpeg to optimized 720p H.264 MP4...")

    raw_videos = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if f.endswith('.webm')]
    if not raw_videos:
        print("Error: No raw video found!")
        return

    latest_video = max(raw_videos, key=os.path.getctime)
    final_output_mp4 = "recordings/client_onboarding_workflow_720p.mp4"

    cmd = [
        "/usr/local/bin/ffmpeg",
        "-y",
        "-i", latest_video,
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-c:v", "libx264",
        "-crf", "24",
        "-preset", "medium",
        "-movflags", "+faststart",
        final_output_mp4
    ]
    subprocess.run(cmd, check=True)
    
    file_size_mb = os.path.getsize(final_output_mp4) / (1024 * 1024)
    print(f"\nSUCCESS! 720p Workflow Video Recorded & Optimized:")
    print(f"File Path: {os.path.abspath(final_output_mp4)}")
    print(f"File Size: {file_size_mb:.2f} MB")

if __name__ == "__main__":
    run_recording()
