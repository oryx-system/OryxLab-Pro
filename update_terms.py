from app import app, set_setting, get_setting

new_policy = """
<div class="lh-sm">
    <h5 class="fw-bold text-center mb-4">[이용 약관 및 개인정보 처리방침]</h5>

    <h6 class="fw-bold text-primary"><i class="fas fa-book-reader me-2"></i>제1조 (시설 이용 수칙)</h6>
    <ol class="small text-muted mb-4">
        <li><strong>이용 시간 준수:</strong> 예약 시간 내에 입실 및 퇴실(정리 포함)을 완료해야 합니다.</li>
        <li><strong>정리 정돈:</strong> 퇴실 시 사용한 물품(책상, 의자, 전자기기 등)을 제자리에 정리합니다.</li>
        <li><strong>입실 체크:</strong> 시설 이용 시 반드시 QR 체크인 또는 스마트 체크인을 진행해야 합니다.</li>
        <li><strong>책임:</strong> 시설물 파손, 분실, 훼손 시 원상복구 또는 배상의 책임이 있습니다.</li>
    </ol>

    <h6 class="fw-bold text-danger"><i class="fas fa-exclamation-circle me-2"></i>제2조 (예약 취소 및 노쇼 정책)</h6>
    <ul class="small text-muted mb-4">
        <li>당일 취소 또는 예고 없는 미방문(No-Show) 발생 시, <strong>향후 30일간 예약이 제한</strong>될 수 있습니다.</li>
    </ul>

    <hr class="my-3">

    <h6 class="fw-bold text-success"><i class="fas fa-user-shield me-2"></i>제3조 (개인정보 수집 및 이용 동의)</h6>
    
    <p class="small fw-bold mt-2">1. 개인정보의 수집 및 이용 목적</p>
    <p class="small text-muted">지혜마루 작은도서관은 시설 예약 및 출입 관리를 위해 아래와 같은 개인정보를 수집합니다.</p>
    
    <p class="small fw-bold mt-3">2. 수집하는 개인정보의 항목</p>
    <ul class="small text-muted">
        <li>필수항목: 이름, 전화번호, 비밀번호(암호화)</li>
        <li>기타: 예약목적, 전자서명, 출입로그</li>
    </ul>

    <p class="small fw-bold mt-3">3. 개인정보의 보유 및 이용 기간 (개정 2026.01.13)</p>
    <p class="small text-muted mb-1">
        이용자의 개인정보는 원칙적으로 개인정보의 수집 및 이용목적이 달성되면 지체 없이 파기합니다. 단, 다음의 정보는 내부 방침에 따라 명시된 기간 동안 보존합니다.
    </p>
    <ul class="small text-muted bg-light p-2 rounded">
        <li><strong>보존 항목:</strong> 예약 이력 (통계 및 이용 분석용)</li>
        <li><strong>보존 기간:</strong> 1년 (365일)</li>
        <li><strong>파기 방법:</strong> 1년 경과 시 이름, 전화번호, 전자서명 등 <u>개인 식별 정보는 복구 불가능한 방법으로 영구 삭제(익명화)</u> 처리되며, 비식별화된 통계 데이터만 남습니다.</li>
    </ul>

    <p class="small fw-bold mt-3">4. 동의 거부 권리</p>
    <p class="small text-muted">귀하는 개인정보 수집 및 이용에 동의하지 않을 권리가 있습니다. 단, 동의를 거부할 경우 시설 예약 및 이용이 제한될 수 있습니다.</p>
</div>
"""

def update_terms():
    with app.app_context():
        print("Updating Privacy Policy...")
        set_setting('privacy_policy', new_policy.strip())
        print("Success! Privacy Policy updated with 1-Year Retention Clause.")

if __name__ == "__main__":
    update_terms()
