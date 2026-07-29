"""WorkShield AWS CDK 애플리케이션 진입점.

1단계에서는 계정 정보를 요구하지 않는 빈 CDK assembly만 합성한다. 실제
foundation/service stack은 3단계에서 이 진입점에 연결한다.
"""

from aws_cdk import App, Stack


app = App()
# CDK CLI는 stack이 하나도 없으면 synth를 실패 처리한다. 이 빈 stack은 3단계의
# foundation/service stack이 추가되기 전까지 계정·리전·secret 없이 진입점을
# 검증하기 위한 placeholder이며 AWS resource를 만들지 않는다.
Stack(app, "WorkShieldSkeleton")
app.synth()
