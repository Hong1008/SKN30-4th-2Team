// Managed by the local WorkShield CDK application.
function handler(event) {
  var request = event.request;
  var uri = request.uri;

  // 확장자가 없는 정적 웹 경로만 SPA entrypoint로 보낸다.
  // API behavior는 별도 CloudFront behavior가 소유하므로 여기서 건드리지 않는다.
  if (!uri.includes(".") && !uri.endsWith("/")) {
    request.uri = "/index.html";
  }

  return request;
}
