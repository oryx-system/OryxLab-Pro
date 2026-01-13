from app import mask_name, mask_phone

def test_masking():
    print("Testing PII Masking...")
    
    # Test Name
    assert mask_name("홍길동") == "홍*동"
    assert mask_name("김철") == "김*"
    assert mask_name("남궁민수") == "남**수"
    print("Name Masking: OK")
    
    # Test Phone
    assert mask_phone("010-1234-5678") == "010-****-5678"
    assert mask_phone("010-123-4567") == "010-***-4567"
    assert mask_phone("01012345678") == "010-****-5678" # Auto format
    assert mask_phone("0101234567") == "010-***-4567"   # Auto format
    assert mask_phone("12345") == "1****"               # Fallback
    print("Phone Masking: OK")

if __name__ == "__main__":
    test_masking()
