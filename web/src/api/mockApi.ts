import { ApiResponse, ReviewSessionData, ReviewData, ResultsData, MetadataData } from '../types';

// TODO(Real API Integration):
// When replacing this mock API with real axios/fetch calls, ensure to configure the client:
// const apiClient = axios.create({
//   baseURL: '/api/v1',
//   withCredentials: true, // IMPORTANT: Required for HttpOnly Cookie session token
// });

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export const mockApi = {
  async getMetadata(): Promise<ApiResponse<MetadataData>> {
    await delay(300);
    return {
      data: {
        schema_version: "1.1",
        updated_at: new Date().toISOString(),
        contract_types: [
          {
            code: "SW_FREELANCE",
            label: "SW 프리랜서 용역",
            description: "SW 프리랜서 도급·용역 계약 비교 기준입니다.",
            enabled_for_mvp: true
          },
          {
            code: "SI_SUBCONTRACT",
            label: "SI 하도급",
            description: "SI 구축 하도급 계약 비교 기준입니다.",
            enabled_for_mvp: true
          },
          {
            code: "SM_SUBCONTRACT",
            label: "SM 하도급",
            description: "SM 운영·유지보수 하도급 계약 비교 기준입니다.",
            enabled_for_mvp: true
          }
        ],
        categories: [
          { code: "CONTRACT_PURPOSE", label: "계약목적" },
          { code: "DELIVERY", label: "납품/검수" },
          { code: "PAYMENT", label: "대금지급" },
          { code: "DELAY_PENALTY", label: "지체상금" },
          { code: "MAINTENANCE", label: "하자보수" },
          { code: "IP", label: "지식재산권" },
          { code: "TERMINATION", label: "계약해지" },
          { code: "COMPENSATION", label: "손해배상" },
          { code: "CONFIDENTIALITY", label: "비밀유지" }
        ],
        result_codes: [
          { code: "NONE", label: "대응 표준조항 있음" },
          { code: "EXTRA", label: "추가·변형 내용 확인" },
          { code: "NO_MATCH", label: "대응 조항 확인 필요" },
          { code: "MISSING", label: "포함 여부 확인 필요" }
        ],
        progress_stages: [
          { code: "PREPARE", label: "검토 준비 중" },
          { code: "BATCH_SEARCH", label: "조항 탐색 및 분류" },
          { code: "RERANK", label: "관련 조항 재정렬" },
          { code: "CLAUSE_REVIEW", label: "검토 진행 중" },
          { code: "MISSING_DETECTION", label: "누락 조항 검출" },
          { code: "RESULT_ASSEMBLY", label: "결과 정리 중" }
        ],
        file_policy: {
          extensions: ["hwp", "hwpx", "pdf", "docx"],
          max_size_bytes: 10485760,
          single_file_only: true,
          encrypted_file_allowed: false
        }
      },
      meta: { request_id: 'meta_req_1', timestamp: new Date().toISOString() }
    }
  },

  async uploadContract(file: File): Promise<ApiResponse<ReviewSessionData>> {
    await delay(1500);
    return {
      data: {
        session_id: 'ses_mock_123',
        review_state: 'TYPE_SELECTION_REQUIRED',
        upload: {
          file_name: file.name,
          size_bytes: file.size,
          extension: file.name.split('.').pop() || '',
        },
        scope_status: 'CONTRACT_TYPE_UNCERTAIN',
        scope_message: '계약 유형을 선택해 주세요.',
        suggested_contract_type: 'SW_FREELANCE',
        selected_contract_type: null,
        selection_source: null,
        candidates: [{ contract_type: 'SW_FREELANCE', evidence_score: 82 }],
        matched_clause_count: 8,
        allowed_actions: ['SELECT_CONTRACT_TYPE'],
        expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
      },
      meta: { request_id: 'req_1', timestamp: new Date().toISOString() }
    };
  },

  async selectContractType(sessionId: string, type: string): Promise<ApiResponse<ReviewSessionData>> {
    await delay(500);
    return {
      data: {
        session_id: sessionId,
        scope_status: 'IN_SCOPE',
        suggested_contract_type: 'SW_FREELANCE',
        selected_contract_type: type,
        selection_source: 'MANUAL',
        review_state: 'READY_TO_REVIEW',
        can_start_review: true,
        candidates: [],
        matched_clause_count: 8,
        scope_message: '',
        allowed_actions: [],
        expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString()
      },
      meta: { request_id: 'req_2', timestamp: new Date().toISOString() }
    };
  },

  async startReview(sessionId: string, idempotencyKey?: string): Promise<ApiResponse<ReviewData>> {
    await delay(1000);
    // TODO(Real API Integration): include idempotencyKey in the headers like:
    // { headers: { 'Idempotency-Key': idempotencyKey } }
    console.log(`[API Mock] startReview called with Idempotency-Key: ${idempotencyKey}`);
    return {
      data: {
        review_id: 'rev_mock_456',
        review_state: 'QUEUED',
        mcp_review_status: null,
        progress: {
          sequence: 0,
          stage: 'PREPARE',
          current: 0,
          total: 100,
          percent: 0,
          message: '검토를 준비하고 있습니다.'
        }
      },
      meta: { request_id: 'req_3', timestamp: new Date().toISOString() }
    };
  },

  async pollReviewStatus(reviewId: string, currentPercent: number): Promise<ApiResponse<ReviewData>> {
    await delay(1000);
    
    let nextPercent = currentPercent + Math.floor(Math.random() * 20) + 10;
    let state = 'REVIEWING';
    let message = '계약 조항을 비교하고 있습니다.';
    
    if (nextPercent >= 100) {
      nextPercent = 100;
      state = 'COMPLETED';
      message = '검토가 완료되었습니다.';
    }

    return {
      data: {
        review_id: reviewId,
        review_state: state,
        mcp_review_status: state === 'COMPLETED' ? 'OK' : null,
        progress: {
          sequence: nextPercent,
          stage: 'CLAUSE_REVIEW',
          current: nextPercent,
          total: 100,
          percent: nextPercent,
          message: message
        }
      },
      meta: { request_id: 'req_4', timestamp: new Date().toISOString() }
    };
  },

  async getResults(reviewId: string): Promise<ApiResponse<ResultsData>> {
    await delay(800);
    return {
      data: {
        review: {
          review_id: reviewId,
          review_state: 'COMPLETED',
          mcp_review_status: 'OK',
          contract_type: 'SW_FREELANCE',
          started_at: new Date(Date.now() - 30000).toISOString(),
          completed_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
          disclaimer: '표준계약서 대비 검토 후보이며 법률 자문이 아닙니다.'
        },
        summary: {
          clause_results: { total: 17, NONE: 10, EXTRA: 4, NO_MATCH: 3 },
          missing_standard_clauses: 2,
          toxic_pattern_candidates: 3
        },
        clause_results: [
          {
            user_clause_id: 'uc_rev_mock_456_1',
            user_clause: '제1조 (근로계약 기간) 본 계약의 근로계약 기간은 계약 체결일로부터 1년으로 하며, 당사자 합의에 따라 연장할 수 있다.',
            deviation: { code: 'NONE', label: '대응 조항 있음' },
            match: {
              status: 'CANDIDATE_SELECTED',
              standard: {
                clause_id: 'sw_freelance-2020-art1',
                contract_type: 'SW_FREELANCE',
                category: { code: 'CONTRACT_PERIOD', label: '계약 기간' },
                title: '계약 기간',
                text: '계약 기간...',
                source: '표준계약서',
                version: '2020'
              }
            },
            explanation: '표준조항과 유사한 기간 설정 구조가 확인됩니다. 연장 조건에 대한 상세 조건을 확인해 주세요.',
            toxic_patterns: []
          },
          {
            user_clause_id: 'uc_rev_mock_456_2',
            user_clause: '제7조 (임금 및 지급 방법) 월 기본급은 금 원으로 하며, 매월 25일에 근로자가 지정한 계좌로 지급한다.',
            deviation: { code: 'EXTRA', label: '추가·변형 내용 확인' },
            match: {
              status: 'CANDIDATE_SELECTED',
              standard: {
                clause_id: 'sw_freelance-2020-art7',
                contract_type: 'SW_FREELANCE',
                category: { code: 'WAGE', label: '임금' },
                title: '임금',
                text: '임금 조항...',
                source: '표준계약서',
                version: '2020'
              }
            },
            explanation: '기본급 금액이 미기재 상태입니다. 표준조항의 임금 항목별 명시 방식과 비교가 필요합니다.',
            toxic_patterns: []
          }
        ],
        missing_standard_clauses: [
          {
            result_type: { code: 'MISSING', label: '포함 여부 확인' },
            standard: {
              clause_id: 'sw_freelance-2020-art34',
              contract_type: 'SW_FREELANCE',
              category: { code: 'SEVERANCE', label: '퇴직금' },
              title: '퇴직금 및 퇴직 절차 관련 조항',
              text: '사용자는 퇴직하는 근로자에게 급여를 지급하기 위하여 퇴직급여제도 중 하나 이상의 제도를 설립·운영하여야 한다.',
              source: '근로기준법 제34조',
              version: '2020'
            },
            explanation: '해당 표준조항의 내용을 계약서 전체에서 찾지 못했습니다.'
          }
        ]
      },
      meta: { request_id: 'req_5', timestamp: new Date().toISOString() }
    };
  },

  async getGrounding(reviewId: string, category: string): Promise<ApiResponse<any>> {
    await delay(600);
    return {
      data: {
        grounding_status: 'OK',
        category: { code: category, label: '법령 카테고리' },
        contract_type: 'SW_FREELANCE',
        items: [
          {
            source_id: 'law_1',
            law_name: '하도급공정화에관한법률',
            article: '제3조',
            text: '원사업자는 수급사업자에게 제조등의 위탁을 하는 경우에는 제2항의 사항을 적은 서면을 수급사업자가 물품등의 납품을 위한 작업을 시작하기 전까지 수급사업자에게 발급하여야 한다.',
            source: '국가법령정보센터',
            source_url: null
          },
          {
            source_id: 'law_2',
            law_name: '소프트웨어진흥법',
            article: '제50조',
            text: '국가기관등의 장은 소프트웨어사업의 계약을 체결하는 경우 공정한 계약의 체결을 위하여 노력하여야 한다.',
            source: '국가법령정보센터',
            source_url: null
          }
        ],
        message: null
      },
      meta: { request_id: 'req_grounding', timestamp: new Date().toISOString() }
    };
  },

  async retryReview(reviewId: string, idempotencyKey?: string): Promise<ApiResponse<ReviewData>> {
    await delay(1000);
    // TODO(Real API Integration): include idempotencyKey in the headers
    console.log(`[API Mock] retryReview called with Idempotency-Key: ${idempotencyKey}`);
    return {
      data: {
        review_id: reviewId,
        review_state: 'QUEUED',
        mcp_review_status: null,
        progress: {
          sequence: 0,
          stage: 'PREPARE',
          current: 0,
          total: 100,
          percent: 0,
          message: '검토를 다시 준비하고 있습니다.'
        }
      },
      meta: { request_id: 'req_retry', timestamp: new Date().toISOString() }
    };
  },

  async chat(reviewId: string, message: string, idempotencyKey?: string): Promise<ApiResponse<any>> {
    await delay(500);
    console.log(`[API Mock] chat called with message: "${message}", Idempotency-Key: ${idempotencyKey}`);
    return {
      data: { reply: "챗봇의 임시 응답입니다." },
      meta: { request_id: 'req_chat', timestamp: new Date().toISOString() }
    };
  },

  async suggestions(reviewId: string, clauseId: string, idempotencyKey?: string): Promise<ApiResponse<any>> {
    await delay(500);
    console.log(`[API Mock] suggestions called for clause: ${clauseId}, Idempotency-Key: ${idempotencyKey}`);
    return {
      data: { suggestions: ["문구 추천 임시 결과 1", "문구 추천 임시 결과 2"] },
      meta: { request_id: 'req_suggestions', timestamp: new Date().toISOString() }
    };
  }
};
