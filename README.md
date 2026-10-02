# Danta

과거 분봉으로 단타 전략을 백테스트하고 정적 HTML 대시보드로 표시합니다.

대시보드: <https://leerazor.github.io/danta/>

## GitHub Pages 배포

저장소 **Settings → Pages → Build and deployment → Source**는 **GitHub Actions**로 설정합니다.
`main`에 대시보드 관련 변경을 push하면 `.github/workflows/pages.yml`이 렌더 테스트 후 HTML을 게시합니다.
**Actions → Deploy dashboard to GitHub Pages → Run workflow**로 수동 배포할 수도 있습니다.

빌드는 기존 `uv.lock`, Python 3.11, `stock_sim/render.py`와 템플릿을 사용합니다.
게시 대상은 `_site/index.html` 하나입니다. GitHub Actions에서는 KIS API를 호출하지 않으며 API 키가 필요하지 않습니다.

### 게시 데이터

- `stock-sim/publish/result.json`이 있으면 해당 결과를 렌더합니다.
- 없으면 `stock-sim/docs/result.example.json`을 사용하며 화면에 **예시 데이터(가짜 수치)**가 표시됩니다.

실제 백테스트 결과로 갱신하려면 백테스트가 끝난 환경에서 공개할 `stock-sim/output/result.json`을
`stock-sim/publish/result.json`으로 복사하고 커밋·push합니다. `meta.is_example`은 원본 값을 유지합니다.
`output/`과 데이터 캐시는 계속 Git에서 제외되며, 실행 결과가 자동으로 서버에 전송되지는 않습니다.
게시된 HTML과 저장소에 커밋한 JSON은 공개됩니다. 결과에는 시뮬레이션 수치만 넣습니다.

저장소 루트에서 예제 HTML을 로컬 생성할 수 있습니다.

```bash
uv run --frozen --project stock-sim python stock-sim/src/stock_sim/render.py \
  --result stock-sim/docs/result.example.json \
  --template stock-sim/templates/dashboard.html.j2 \
  --out _site/index.html
```

## Cloudflare 도메인 연결

도메인을 Cloudflare에 등록하고 네임서버 연결이 활성화된 상태에서 진행합니다.

1. GitHub 저장소 **Settings → Pages → Custom domain**에 사용할 도메인을 먼저 저장합니다.
2. Cloudflare DNS에서 아래 레코드를 설정합니다. 예시는 `danta.example.com`이며 실제 도메인으로 바꿉니다.

   | 유형 | 이름 | 대상 | 프록시 상태 |
   | --- | --- | --- | --- |
   | CNAME | danta | leerazor.github.io | DNS only |

   CNAME 대상에는 `https://`나 `/danta`를 붙이지 않습니다.
   루트 도메인(`example.com`)을 사용하면 `@` 이름으로 A 레코드 네 개를 등록합니다:
   `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`.
3. GitHub의 DNS 확인과 인증서 발급이 완료되면 **Enforce HTTPS**를 켭니다.

처음에는 `DNS only`로 직접 연결을 확인합니다. 이 상태에서 Cloudflare는 DNS를 관리하고 웹 요청은 GitHub Pages로 갑니다.
Actions 배포에서는 `CNAME` 파일 대신 GitHub Pages의 **Custom domain** 설정을 사용합니다.
DNS 반영과 HTTPS 준비에는 최대 24시간이 걸릴 수 있습니다.

참고: [GitHub 사용자 지정 도메인 안내](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site),
[Cloudflare 프록시 상태](https://developers.cloudflare.com/dns/proxy-status/).
