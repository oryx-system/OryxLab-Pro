from app import app, perform_cleanup
import sys

def main():
    print("Running Cleanup Job...")
    with app.app_context():
        try:
            # Default to 365 days (1 Year)
            perform_cleanup(days=365)
            print("Cleanup Job Success")
        except Exception as e:
            print(f"Cleanup Job Failed: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
