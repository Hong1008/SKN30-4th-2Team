export type Screen =
  | 'upload-and-type'
  | 'out-of-scope'
  | 'processing'
  | 'results'
  | 'clause-detail'
  | 'chatbot'

export type ResultCode = 'NONE' | 'EXTRA' | 'NO_MATCH' | 'MISSING'
export type ReviewState = 'QUEUED' | 'REVIEWING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'EXPIRED'
export type ReviewSessionState =
  | 'ANALYZING_CONTRACT_TYPE'
  | 'TYPE_SELECTION_REQUIRED'
  | 'OUT_OF_SCOPE_CONFIRMATION_REQUIRED'
  | 'READY_TO_REVIEW'
  | 'REUPLOAD_REQUIRED'
  | 'FAILED'
  | 'EXPIRED'
export type ScopeStatus = 'IN_SCOPE' | 'CONTRACT_TYPE_UNCERTAIN' | 'OUT_OF_SCOPE' | 'EMPTY_DOCUMENT'
export type AllowedAction = 'SELECT_CONTRACT_TYPE' | 'CONFIRM_OUT_OF_SCOPE' | 'START_REVIEW' | 'REUPLOAD'
export type SelectionSource = 'SUGGESTED' | 'CANDIDATE' | 'MANUAL'

export interface ClauseResult {
  id: string
  article: string
  excerpt: string
  status: ResultCode
  category: string
  summary: string
  toxic_patterns?: {code: string; label: string}[]
  categoryCode?: string
  standardTitle?: string
  standardText?: string
  standardSource?: string
  standardClauseId?: string
  standardVersion?: string
  matchStatus: 'CANDIDATE_SELECTED' | 'NO_CANDIDATE'
}

export interface MissingClauseResult {
  id: string
  category: string
  title: string
  text: string
  explanation: string
}

// --- API Types based on api-draft.md ---

export interface ApiResponse<T> {
  data: T;
  meta: {
    request_id: string;
    timestamp: string;
  };
}

export interface ApiError {
  code: string;
  message?: string;
  field?: string | null;
  retryable?: boolean;
  next_action?: string;
  details?: unknown;
}

export interface ReviewSessionData {
  session_id: string;
  review_state: ReviewSessionState;
  upload?: {
    file_name: string;
    size_bytes: number;
    extension: string;
  };
  scope_status: ScopeStatus | null;
  scope_message: string | null;
  suggested_contract_type: string | null;
  selected_contract_type: string | null;
  selection_source: SelectionSource | null;
  candidates: ContractTypeCandidate[];
  matched_clause_count: number;
  exclusion_markers: string[];
  out_of_scope_confirmed_at: string | null;
  allowed_actions: AllowedAction[];
  expires_at: string;
  can_start_review: boolean;
}

export interface ContractTypeCandidate {
  contract_type: string;
  evidence_score: number;
}

export interface ReviewProgress {
  sequence: number;
  stage: string;
  current: number;
  total: number | null;
  percent: number;
  message?: string | null;
}

export interface ReviewSseEvent {
  review_id: string;
  sequence: number;
  review_state: ReviewState;
  stage: string | null;
  current: number | null;
  total: number | null;
  percent: number | null;
  message?: string | null;
  mcp_review_status?: string | null;
  error?: ApiError | null;
}

export interface ReviewCreateData {
  review_id: string;
  review_state: ReviewState;
  session_id: string;
  retry_of?: string | null;
}

export interface ReviewData {
  review_id: string;
  session_id: string;
  review_state: ReviewState;
  mcp_review_status: string | null;
  result: unknown | null;
  progress: ReviewProgress | null;
  error: ApiError | null;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string;
}

export interface ReviewCancelData {
  review_id: string;
  review_state: ReviewState;
  deleted: boolean;
}

export interface ResultsData {
  review: {
    review_id: string;
    review_state: 'COMPLETED';
    mcp_review_status: string;
    contract_type: string;
    started_at: string | null;
    completed_at: string | null;
    expires_at: string;
    disclaimer: string;
  };
  summary: {
    clause_results: {
      total: number;
      NONE: number;
      EXTRA: number;
      NO_MATCH: number;
    };
    missing_standard_clauses: number;
    toxic_pattern_candidates: number;
  };
  clause_results: ReviewClauseResultData[];
  missing_standard_clauses: MissingStandardClauseData[];
}

export interface CodeLabel {
  code: string;
  label: string;
}

export interface StandardClauseData {
  clause_id: string;
  contract_type: string;
  category: CodeLabel;
  title: string;
  text: string;
  source: string;
  version: string;
}

export interface ReviewClauseResultData {
  user_clause_id: string;
  user_clause: string;
  deviation: CodeLabel;
  match: {
    status: 'CANDIDATE_SELECTED' | 'NO_CANDIDATE';
    standard?: StandardClauseData | null;
  };
  explanation: string;
  toxic_patterns: CodeLabel[];
}

export interface MissingStandardClauseData {
  result_type: CodeLabel;
  standard: StandardClauseData;
  explanation: string;
}

export interface ContractTypeMeta {
  code: string;
  label: string;
  description?: string | null;
  enabled_for_mvp?: boolean | null;
}

export interface MetaCodeLabel {
  code: string;
  label: string;
}

export interface StatusPresentation extends MetaCodeLabel {
  message?: string | null;
  retryable?: boolean | null;
  next_action?: string | null;
}

export interface CategoryMeta extends MetaCodeLabel {
  description?: string | null;
  anchors?: string[];
}

export interface ToxicPatternMeta extends MetaCodeLabel {
  category?: string | null;
  example_count: number;
}

export interface FeatureFlags {
  chat: boolean;
  basic_suggestion: boolean;
  confidence_score: boolean;
  suggestion_edit: boolean;
  single_clause_rereview: boolean;
  server_side_cancel: boolean;
}

export interface FilePolicyMeta {
  extensions: string[];
  max_size_bytes: number;
  single_file_only: boolean;
  encrypted_file_allowed: boolean;
}

export interface MetadataData {
  schema_version: string;
  updated_at: string;
  contract_types: ContractTypeMeta[];
  categories: CategoryMeta[];
  toxic_patterns: ToxicPatternMeta[];
  scope_statuses: ScopeStatus[];
  review_states: string[];
  result_codes: string[];
  result_code_details: MetaCodeLabel[];
  progress_stages: string[];
  progress_stage_details: MetaCodeLabel[];
  grounding_statuses: string[];
  grounding_status_details?: StatusPresentation[];
  chat_outcomes: string[];
  chat_outcome_details?: StatusPresentation[];
  draft_outcomes: string[];
  draft_outcome_details?: StatusPresentation[];
  error_codes: string[];
  selection_sources: string[];
  next_actions: string[];
  file_policy: FilePolicyMeta;
  features: FeatureFlags;
}

export interface GroundingData {
  grounding_status: string;
  category: CodeLabel;
  contract_type: string;
  message?: string | null;
  retryable?: boolean | null;
  next_action?: string | null;
  items: GroundingItem[];
}

export interface GroundingItem {
  source_id: string;
  law_name?: string | null;
  article?: string | null;
  text: string;
  source?: string | null;
  source_url?: string | null;
}

export interface ChatSource {
  type: 'USER_CLAUSE' | 'STANDARD_CLAUSE' | 'LAW';
  id?: string | null;
  display_label?: string | null;
  clause_number?: string | null;
  title?: string | null;
  category?: string | null;
  law_name?: string | null;
  article?: string | null;
  source_url?: string | null;
}

export interface ChatHistoryMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatResponse {
  outcome: string;
  answer: string | null;
  sources: ChatSource[];
  refused: boolean;
  limitations: string[];
  tool_status: string;
  disclaimer: string;
  message?: string | null;
  retryable?: boolean | null;
  next_action?: string | null;
}

export interface RequiredConfirmation {
  field: string;
  placeholder: string;
}

export interface SuggestionResponse {
  outcome: string;
  text: string | null;
  purpose: string | null;
  key_changes: string[];
  used_source_keys: string[];
  user_clause_ids: string[];
  standard_clause_ids: string[];
  grounding_source_ids: string[];
  required_confirmations: RequiredConfirmation[];
  missing_inputs: string[];
  disclaimer: string;
  message?: string | null;
  retryable?: boolean | null;
  next_action?: string | null;
}
