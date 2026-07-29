# 애플리케이션 배포와 롤백

GitHub Actions는 기존 인프라에 검증된 artifact를 배포한다. AWS·RunPod
리소스 생성·삭제와 runtime secret 조회는 workflow에서 수행하지 않는다.

모든 운영 배포 workflow는 같은 production concurrency group을 사용하고,
동시에 둘 이상 실행하지 않는다.

## Container 이미지 게시

`publish-containers.yml`을 수동 실행한다.

| 입력 | 의미 |
| --- | --- |
| `source_ref` | build할 Git ref |
| `image_tag` | API·MCP에 공통으로 붙일 불변 논리 tag |

workflow는 submodule을 포함한 ref를 checkout하고 API·MCP 이미지를 GHCR에
게시한다. 같은 tag가 이미 다른 digest를 가리키면 덮어쓰지 않고 실패한다.
AWS credential은 사용하지 않는다.

```text
ghcr.io/<owner>/<repository>/api:<image_tag>
ghcr.io/<owner>/<repository>/mcp:<image_tag>
```

운영 배포에는 mutable `latest`를 사용하지 않는다.
EC2에는 GitHub package token을 저장하지 않으므로 API·MCP GHCR package는
익명 pull이 가능한 visibility여야 한다. private package를 사용하려면 별도의
최소권한 pull credential 설계 없이는 배포하지 않는다.

## Container 배포

`deploy-containers.yml`에 기존 `image_tag`를 입력한다.

1. API·MCP tag가 모두 존재하는지 확인하고 digest로 해석한다.
2. GitHub OIDC로 제한된 deploy role을 맡는다.
3. 고정 SSM Document에 API/MCP digest와 논리 tag만 전달한다.
4. EC2가 image를 pull하고 Compose를 갱신한다.
5. API·MCP health 성공 후 활성 tag와 digest를 기록한다.
6. 실패하면 직전 활성 digest를 다시 적용한다.

Run Command parameter와 workflow 로그에는 secret 값을 넣지 않는다. EC2가
instance role로 runtime secret과 binding을 읽는다.

## Container 롤백

`rollback-containers.yml`에 되돌릴 기존 `image_tag`를 입력한다.

- source checkout이나 rebuild를 하지 않는다.
- API와 MCP image가 모두 존재해야 한다.
- 일반 배포와 같은 digest 확인, SSM 적용, health, 자동복구 경로를 사용한다.
- DB schema를 자동으로 되돌리지 않는다. 호환되지 않는 migration이 포함된
  release는 별도 데이터 복구 계획 없이는 롤백하지 않는다.

## Web 배포

Web은 Docker image가 아니라 Vite build artifact로 배포한다.
`deploy-web.yml` 입력은 다음과 같다.

| 입력 | 의미 |
| --- | --- |
| `source_ref` | Web을 build할 Git ref |
| `web_release_tag` | S3에 보존할 불변 release 식별자 |

workflow는 `npm ci`, `npm run build` 후 artifact와 manifest를 다음 release
prefix에 저장한다.

```text
s3://<web-bucket>/releases/<web_release_tag>/
```

동일 tag의 기존 manifest가 다른 commit 또는 content hash를 가지면
덮어쓰지 않는다. 보존된 release를 live prefix로 승격한 뒤 CloudFront
invalidation을 수행한다.

## Web 롤백

`rollback-web.yml`에 기존 `web_release_tag`를 입력한다.

- checkout과 rebuild 없이 S3 release artifact를 사용한다.
- manifest나 artifact가 없으면 자동 재생성하지 않고 실패한다.
- release를 live prefix로 다시 승격한 뒤 CloudFront invalidation을 실행한다.

정상 release와 롤백 후보의 GHCR image와 S3 artifact를 삭제하지 않는다.

## MCP Embed/Rerank 이미지

Embed/Rerank worker 이미지는 MCP submodule의 `publish-pod-image.yml`을 수동
실행해 게시한다.

```text
ghcr.io/<owner>/<mcp-repository>/embed-rerank:<submodule-commit-sha>
ghcr.io/<owner>/<mcp-repository>/embed-rerank:latest
```

workflow는 `deploy/runpod_worker/Pod.Dockerfile`을 build하고 SHA image 게시가
완료된 뒤에만 `latest`를 갱신한다. digest는 workflow summary에서 확인한다.
이 workflow는 RunPod 관리 키를 사용하거나 Pod/template을 변경하지 않는다.

새 `latest`를 실행 중 Pod에 적용하려면 로컬에서 다음을 실행한다.

```bash
just infra-runpod-replace embed profile=<profile> environment=prod
```

## 배포 후 확인

- workflow가 기록한 image digest와 활성 runtime digest가 일치하는가
- API·MCP live/ready와 API→MCP 요청이 성공하는가
- Web 정적 asset과 SPA rewrite가 정상인가
- `/api/*` 오류가 SPA HTML `200`으로 바뀌지 않는가
- CloudFront invalidation이 완료됐는가
- SSE가 Nginx buffering 없이 유지되는가

인프라 변경이 필요하면 workflow 권한을 넓히지 말고
[로컬 프로비저닝](../infra/provisioning.md) 절차를 사용한다.
