/* =========================================================
   Jungle Laundry Dashboard 2.0 - Application Logic
   ========================================================= */

// 환경에 따른 API URL 결정 (로컬 프록시 서버 우선, fallback으로 직접 호출)
const isLocalServer = window.location.protocol.startsWith('http');
const API_STATUS = isLocalServer ? '/api/status' : 'https://miracle-beautifully-onto-ser.trycloudflare.com/api/status';
const API_STATS  = isLocalServer ? '/api/stats?days=7' : 'https://miracle-beautifully-onto-ser.trycloudflare.com/api/stats?days=7';
const REFRESH_INTERVAL_SEC = 20;

// 워시타워 9대 메타데이터
const TOWERS = [
  { id: 1, name: '워시타워_1', zone: 'men',    label: '1호기', zoneName: '남성 전용' },
  { id: 2, name: '워시타워_2', zone: 'men',    label: '2호기', zoneName: '남성 전용' },
  { id: 3, name: '워시타워_3', zone: 'men',    label: '3호기', zoneName: '남성 전용' },
  { id: 4, name: '워시타워_4', zone: 'men',    label: '4호기', zoneName: '남성 전용' },
  { id: 5, name: '워시타워_5', zone: 'men',    label: '5호기', zoneName: '남성 전용' },
  { id: 6, name: '워시타워_6', zone: 'common', label: '6호기', zoneName: '공용' },
  { id: 7, name: '워시타워_7', zone: 'common', label: '7호기', zoneName: '공용' },
  { id: 8, name: '워시타워_8', zone: 'women',  label: '8호기', zoneName: '여성 전용' },
  { id: 9, name: '워시타워_9', zone: 'women',  label: '9호기', zoneName: '여성 전용' },
];

// 초기 즉시 렌더링용 최신 실시간 스냅샷
const INITIAL_STATUS_SNAPSHOT = {
  "워시타워_1":{"washer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0},"cycle":{"cycleCount":39}},"dryer":{"runState":{"currentState":"ERROR"},"timer":{"remainHour":1,"remainMinute":26},"error":"EMPTY_WATER_ALERT_ERROR"}},
  "워시타워_2":{"washer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0},"cycle":{"cycleCount":13}},"dryer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0}}},
  "워시타워_3":{"washer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0},"cycle":{"cycleCount":29}},"dryer":{"runState":{"currentState":"PAUSE"},"timer":{"remainHour":0,"remainMinute":42}}},
  "워시타워_4":{"washer":{"runState":{"currentState":"RUNNING"},"timer":{"remainHour":0,"remainMinute":42},"cycle":{"cycleCount":33}},"dryer":{"runState":{"currentState":"WRINKLE_CARE"},"timer":{"remainHour":0,"remainMinute":0}}},
  "워시타워_5":{"washer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0},"cycle":{"cycleCount":24}},"dryer":{"runState":{"currentState":"ERROR"},"timer":{"remainHour":0,"remainMinute":51},"error":"EMPTY_WATER_ALERT_ERROR"}},
  "워시타워_6":{"washer":{"runState":{"currentState":"SPINNING"},"timer":{"remainHour":0,"remainMinute":5},"cycle":{"cycleCount":55}},"dryer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0}}},
  "워시타워_7":{"washer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0},"cycle":{"cycleCount":46}},"dryer":{"runState":{"currentState":"RUNNING"},"timer":{"remainHour":1,"remainMinute":34}}},
  "워시타워_8":{"washer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0},"cycle":{"cycleCount":14}},"dryer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0}}},
  "워시타워_9":{"washer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0},"cycle":{"cycleCount":27}},"dryer":{"runState":{"currentState":"POWER_OFF"},"timer":{"remainHour":0,"remainMinute":0}}}
};

const INITIAL_STATS_SNAPSHOT = {
  "days": 7,
  "counts": [
    {"device":"워시타워_1","id":1,"zone":"men","type":"dryer","count":46},{"device":"워시타워_1","id":1,"zone":"men","type":"washer","count":19},
    {"device":"워시타워_2","id":2,"zone":"men","type":"dryer","count":41},{"device":"워시타워_2","id":2,"zone":"men","type":"washer","count":37},
    {"device":"워시타워_3","id":3,"zone":"men","type":"dryer","count":41},{"device":"워시타워_3","id":3,"zone":"men","type":"washer","count":36},
    {"device":"워시타워_4","id":4,"zone":"men","type":"dryer","count":41},{"device":"워시타워_4","id":4,"zone":"men","type":"washer","count":42},
    {"device":"워시타워_5","id":5,"zone":"men","type":"dryer","count":63},{"device":"워시타워_5","id":5,"zone":"men","type":"washer","count":41},
    {"device":"워시타워_6","id":6,"zone":"common","type":"dryer","count":54},{"device":"워시타워_6","id":6,"zone":"common","type":"washer","count":37},
    {"device":"워시타워_7","id":7,"zone":"common","type":"dryer","count":59},{"device":"워시타워_7","id":7,"zone":"common","type":"washer","count":40},
    {"device":"워시타워_8","id":8,"zone":"women","type":"dryer","count":28},{"device":"워시타워_8","id":8,"zone":"women","type":"washer","count":30},
    {"device":"워시타워_9","id":9,"zone":"women","type":"dryer","count":31},{"device":"워시타워_9","id":9,"zone":"women","type":"washer","count":22}
  ],
  "totals": {"dryer": 404, "washer": 304},
  "recent": [
    {"device":"워시타워_3","type":"dryer","event":"end","state":"PAUSE","time":"2026-09-01 14:43:09"},
    {"device":"워시타워_4","type":"washer","event":"start","state":"RUNNING","time":"2026-09-01 14:43:09"},
    {"device":"워시타워_7","type":"dryer","event":"start","state":"RUNNING","time":"2026-09-01 14:33:00"},
    {"device":"워시타워_7","type":"washer","event":"end","state":"END","time":"2026-09-01 14:22:44"},
    {"device":"워시타워_6","type":"dryer","event":"end","state":"END","time":"2026-09-01 14:17:35"},
    {"device":"워시타워_3","type":"dryer","event":"start","state":"RUNNING","time":"2026-09-01 14:17:35"},
    {"device":"워시타워_6","type":"washer","event":"start","state":"RUNNING","time":"2026-09-01 14:07:34"},
    {"device":"워시타워_5","type":"dryer","event":"error","state":"ERROR","time":"2026-09-01 13:11:27"},
    {"device":"워시타워_1","type":"dryer","event":"error","state":"ERROR","time":"2026-09-01 12:56:03"}
  ]
};

let globalStatusData = INITIAL_STATUS_SNAPSHOT;
let globalStatsData = INITIAL_STATS_SNAPSHOT;
let currentZoneFilter = 'all';
let usageChartInstance = null;

// DOM 요소
const washtowerGrid = document.getElementById('washtowerGrid');
const liveDot = document.getElementById('liveDot');
const statusText = document.getElementById('statusText');
const syncTime = document.getElementById('syncTime');
const btnRefresh = document.getElementById('btnRefresh');

// 1. 상태 텍스트
const STATE_TRANSLATION = {
  POWER_OFF:    { label: '대기 중 (사용 가능)', isFree: true, isError: false },
  INITIAL:      { label: '준비 완료',          isFree: true, isError: false },
  COMPLETE:     { label: '세탁 완료 (수거 대기)', isFree: false, isError: false },
  RUNNING:      { label: '작동 중',             isFree: false, isError: false },
  WASHING:      { label: '세탁 중',             isFree: false, isError: false },
  RINSING:      { label: '헹굼 중',             isFree: false, isError: false },
  SPINNING:     { label: '탈수 중',             isFree: false, isError: false },
  DRYING:       { label: '건조 중',             isFree: false, isError: false },
  COOLING:      { label: '쿨링 중',             isFree: false, isError: false },
  WRINKLE_CARE: { label: '구김 방지 중',        isFree: false, isError: false },
  PAUSE:        { label: '일시정지',           isFree: false, isError: false },
  ERROR:        { label: '기기 점검/에러',       isFree: false, isError: true },
};

// 🌟 LG 트롬 워시타워 코스 사전 및 번역기
const COURSE_TRANSLATION = {
  STANDARD: '표준 세탁 (터보샷)',
  NORMAL: '표준 세탁 (터보샷)',
  TURBO_SHOT: '터보샷 39분',
  SPEED_WASH: '소량 급속',
  AI_DD: 'AI 맞춤 세탁 (AI DD™)',
  AI_CUSTOM: 'AI 맞춤 세탁 (AI DD™)',
  TOWEL: '타월 세탁',
  BEDDING: '이불 세탁 (대용량)',
  DUVET: '이불 세탁 (대용량)',
  DELICATE: '울/섬세',
  WOOL: '울/섬세',
  TUB_CLEAN: '통살균 케어',
  RINSE_SPIN: '헹굼+탈수',

  STANDARD_DRY: '표준 건조 (AI 센서)',
  AI_DRY: 'AI 맞춤 건조',
  FAST_DRY: '쾌속 건조',
  BEDDING_DRY: '이불 건조',
  TOWEL_DRY: '타월 건조',
  TIME_DRY: '시간 건조',
  AIR_REFRESH: '에어 살균',
  WRINKLE_CARE: '구김 방지 케어'
};

function getUnitCourseLabel(unitType, unitData, runState, isFloorplan = false) {
  const isRunning = isUnitRunning(runState) || runState === 'WRINKLE_CARE' || runState === 'PAUSE' || runState === 'ERROR';
  if (!isRunning && runState === 'POWER_OFF') return null;

  const rawCourse = unitData.course || unitData.runState?.course || unitData.cycleType;
  if (rawCourse && COURSE_TRANSLATION[rawCourse]) {
    const full = COURSE_TRANSLATION[rawCourse];
    return isFloorplan ? full.replace(/\s*\(.*?\)/g, '') : full;
  }
  if (rawCourse) return isFloorplan ? String(rawCourse).replace(/\s*\(.*?\)/g, '') : rawCourse;

  if (runState === 'WRINKLE_CARE') return isFloorplan ? '구김 방지' : '구김 방지 케어';
  if (unitType === 'washer') {
    if (runState === 'SPINNING') return isFloorplan ? 'AI 맞춤' : 'AI 맞춤 세탁 (AI DD™)';
    return isFloorplan ? '표준 세탁' : '표준 세탁 (터보샷)';
  }
  if (unitType === 'dryer') {
    if (runState === 'PAUSE') return isFloorplan ? '이불 건조' : '이불 건조 (대용량)';
    return isFloorplan ? '표준 건조' : '표준 건조 (AI 센서)';
  }
  return isFloorplan ? '표준 코스' : '표준 코스';
}

// 🌟 LG 트롬 워시타워 (일체형 자동 직배수 방식) 전용 1분 해결 가이드 사전
const ERROR_DIAGNOSTICS = {
  EMPTY_WATER_ALERT_ERROR: {
    title: '건조기 자동 배수 이상 (배수 호스 꺾임 / 배관 막힘)',
    short: '건조기 배수관 점검',
    icon: '🚫',
    productPart: '워시타워 후면 건조기 직배수 호스 & 하단 배수구',
    cause: 'LG 워시타워는 물통이 없는 [자동 직배수] 구조입니다. 이 에러는 후면 배수 호스가 꺾였거나, 필터 먼지 과다/배관 압력으로 응축수가 빠져나가지 못할 때 발생합니다.',
    solution: [
      '<b>[직배수 호스 점검]</b> 워시타워 후면/바닥의 건조기 배수 호스가 꺾이거나 무거운 것에 눌려있는지 확인하고 반듯하게 폅니다.',
      '<b>[2중 필터 청소]</b> 건조기 도어 안쪽 하단의 2중 안심 먼지 필터에 보풀이 꽉 차면 응축수 펌핑 센서에 부하가 걸리므로 필터 먼지를 제거합니다.',
      '<b>[하수구 배수 확인]</b> 바닥 배수 트랩으로 물이 원활하게 흘러나가는지 확인합니다.',
      '<b>[재가동]</b> 중앙 <b>[Center Control™]</b> 패널의 건조기 <b>[동작/일시정지 ▶]</b> 버튼을 터치하여 건조를 재개합니다.'
    ]
  },
  FILTER_CLEAN_ERROR: {
    title: '건조기 2중 안심 먼지 필터 막힘 (배관/IF 에러)',
    short: '먼지 필터 청소 필요',
    icon: '🧹',
    productPart: '상단 건조기 도어 안쪽 하단 입구 (내부+외부 2중 필터)',
    cause: '2중 필터망에 보풀이 누적되어 공기 순환이 차단되고 응축수 순환에 부하가 걸렸습니다.',
    solution: [
      '<b>[내부 필터 분리]</b> 상단 건조기 도어를 열고 하단 입구의 내부 필터를 위로 쏙 들어 올립니다.',
      '<b>[외부 필터 분리]</b> 내부 필터 안쪽에 포개어진 외부 필터도 함께 꺼내어 2개로 분리합니다.',
      '<b>[먼지 제거 & 세척]</b> 보풀을 털어낸 뒤 흐르는 미온수로 필터망을 부드럽게 세척합니다.',
      '<b>[완전 건조 후 장착]</b> 그늘에서 물기를 <b>완전히 바짝 말린 후</b>, 외부 필터 안에 내부 필터를 끼워 장착구에 "딸깍" 소리가 나게 넣습니다.'
    ]
  },
  DRAIN_ERROR: {
    title: '세탁기 배수 펌프 이상 (OE 에러)',
    short: '하단 배수 펌프 거름망 청소',
    icon: '⚠️',
    productPart: '하단 세탁기 전면 좌측 하단 [서비스 커버]',
    cause: '하단 배수 펌프 거름망에 동전, 머리핀, 섬유 이물질이 끼어 세탁수 배출이 막혔습니다.',
    solution: [
      '<b>[서비스 커버 열기]</b> 하단 세탁기 좌측 하단의 사각 서비스 커버를 손으로 눌러 엽니다.',
      '<b>[잔수 제거]</b> 얇은 잔수 호스를 빼내고 마개를 열어 대야나 바닥에 고인 물을 완전히 뺍니다.',
      '<b>[거름망 청소]</b> 둥근 펌프 캡을 반시계 방향(왼쪽)으로 돌려 빼낸 뒤 낀 이물질을 제거하고 물세척합니다.',
      '<b>[원위치]</b> 펌프 캡을 시계 방향으로 꽉 잠그고 잔수 호스 마개를 닫은 후 커버를 닫습니다.'
    ]
  },
  UNBALANCE_ERROR: {
    title: '세탁물 뭉침 및 균형 이상 (UE 에러)',
    short: '세탁물 골고루 펴기',
    icon: '⚖️',
    productPart: '하단 세탁기 드럼 내부',
    cause: '이불이나 큰 빨랫감이 한쪽으로 쏠려 고속 탈수 시 진동 방지를 위해 정지되었습니다.',
    solution: [
      '<b>[도어 열기]</b> 세탁기 도어를 열고 한쪽으로 뭉친 옷감/이불을 고르게 펴서 재배치합니다.',
      '<b>[재가동]</b> 도어를 닫고 중앙 센터 컨트롤에서 [탈수] 코스를 선택하여 다시 동작시킵니다.'
    ]
  },
  DOOR_OPEN_ERROR: {
    title: '도어 덜 닫힘 감지 (dE 에러)',
    short: '도어 밀착 닫기',
    icon: '🚪',
    productPart: '세탁기 / 건조기 도어 래치',
    cause: '도어 고무 패킹 틈새에 옷감이 끼었거나 도어가 덜 닫혔습니다.',
    solution: [
      '도어 틈새에 낀 옷감이 없는지 확인하고, 도어를 <b>"딸깍"</b> 소리가 날 때까지 꾹 눌러 닫아주세요.'
    ]
  }
};

function getErrorDiagnostic(errCode) {
  if (!errCode) return null;
  return ERROR_DIAGNOSTICS[errCode] || {
    title: `기기 점검 필요 (${errCode})`,
    short: '점검 필요',
    icon: '⚠️',
    productPart: 'LG 워시타워 본체',
    cause: '시스템 점검이 필요합니다.',
    solution: ['전원을 껐다 켜거나 운영진에게 문의해 주세요.']
  };
}

// LG 공식 권장: 세탁기 통살균은 누적 30회마다 1회 권장
function getLgCareStatus(cycleCount) {
  const count = typeof cycleCount === 'number' ? cycleCount : 0;
  const LG_RECOMMENDED_LIMIT = 30;
  const percent = Math.min(100, Math.round((count / LG_RECOMMENDED_LIMIT) * 100));

  if (count >= 30) {
    return {
      status: 'danger',
      label: '통살균 청소 필요',
      badgeClass: 'care-danger',
      icon: '🚨',
      percent: percent,
      desc: `누적 ${count}회 가동 (LG 권장 30회 초과! 세탁조 클리너 통살균 필수)`
    };
  } else if (count >= 20) {
    return {
      status: 'warning',
      label: '통살균 청소 임박',
      badgeClass: 'care-warning',
      icon: '🟡',
      percent: percent,
      desc: `누적 ${count}회 가동 (곧 30회 도달, 청소 준비)`
    };
  } else {
    return {
      status: 'good',
      label: '관리 상태 양호',
      badgeClass: 'care-good',
      icon: '🟢',
      percent: percent,
      desc: `누적 ${count}회 가동 (정상 상태)`
    };
  }
}

function formatTimer(remainH, remainM) {
  if (!remainH && !remainM) return '';
  if (remainH > 0) return `${remainH}시간 ${remainM}분`;
  return `${remainM}분`;
}

function isUnitFree(state) {
  return ['POWER_OFF', 'INITIAL', 'COMPLETE'].includes(state);
}

function isUnitRunning(state) {
  return ['RUNNING', 'WASHING', 'RINSING', 'SPINNING', 'DRYING', 'COOLING', 'WRINKLE_CARE'].includes(state);
}

// 실질적인 세탁/건조 가동 중 여부 (구김 방지, 대기, 에러, 남은시간 0분 제외)
function isUnitCycleActive(state, remainMinutes) {
  if (!state || ['POWER_OFF', 'INITIAL', 'COMPLETE', 'END', 'ERROR', 'WRINKLE_CARE'].includes(state)) {
    return false;
  }
  return ['RUNNING', 'WASHING', 'RINSING', 'SPINNING', 'DRYING', 'COOLING', 'PAUSE'].includes(state) && remainMinutes > 0;
}

// 🔔 알림 버튼 동적 렌더러 (구김 방지 및 5분 이하 스마트 라벨 대응)
function renderUnitAlarmButton(towerId, unitType, deviceName, remainMinutes, runState, isFloorplan = false, isModal = false) {
  const isAlarm = myLaundryAlarms.some(a => a.key === `${towerId}_${unitType}`);
  const isCycleActive = isUnitCycleActive(runState, remainMinutes);

  // 이미 알림이 켜져 있는 상태라면 취소 가능하도록 항상 노출
  if (isAlarm) {
    if (isModal) {
      return `<button class="btn-unit-alarm modal-alarm-btn alarm-active" onclick="toggleLaundryAlarm(${towerId}, '${unitType}', '${deviceName}', ${remainMinutes});">🔔 ${unitType === 'washer' ? '세탁기' : '건조기'} 알림 등록됨 (ON)</button>`;
    }
    return `<button class="btn-unit-alarm alarm-active" onclick="event.stopPropagation(); toggleLaundryAlarm(${towerId}, '${unitType}', '${deviceName}', ${remainMinutes})" title="내 알림 해제">🔔 내 알림 ON</button>`;
  }

  // 가동 중이 아니거나 구김 방지 상태이거나 남은 시간이 0분이면 버튼 노출 안 함
  if (!isCycleActive || remainMinutes <= 0 || runState === 'WRINKLE_CARE') {
    return '';
  }

  // 1) 5분 초과 남아있을 때: [🔔 5분전]
  if (remainMinutes > 5) {
    if (isModal) {
      return `<button class="btn-unit-alarm modal-alarm-btn" onclick="toggleLaundryAlarm(${towerId}, '${unitType}', '${deviceName}', ${remainMinutes});">🔔 ${unitType === 'washer' ? '세탁기' : '건조기'} 5분전 알림 등록</button>`;
    }
    const label = isFloorplan ? '🔔 5분전' : '🔔 5분전 알림';
    return `<button class="btn-unit-alarm" onclick="event.stopPropagation(); toggleLaundryAlarm(${towerId}, '${unitType}', '${deviceName}', ${remainMinutes})" title="완료 5분 전 및 완료 시 스마트 알림">${label}</button>`;
  }

  // 2) 5분 이하 남아있을 때: [🔔 완료 알림]
  if (isModal) {
    return `<button class="btn-unit-alarm modal-alarm-btn" onclick="toggleLaundryAlarm(${towerId}, '${unitType}', '${deviceName}', ${remainMinutes});">🔔 ${unitType === 'washer' ? '세탁기' : '건조기'} 완료 알림 등록</button>`;
  }
  const label = isFloorplan ? '🔔 완료알림' : '🔔 완료 알림';
  return `<button class="btn-unit-alarm" onclick="event.stopPropagation(); toggleLaundryAlarm(${towerId}, '${unitType}', '${deviceName}', ${remainMinutes})" title="세탁/건조 완료 즉시 스마트 알림">${label}</button>`;
}

// 2. 메인 데이터 로더 (로컬 프록시 -> Cloudflare 원격 터널 -> 내장 스냅샷 3중 안전망)
async function loadDashboardData() {
  btnRefresh.classList.add('spinning');
  try {
    let statusRes, statsRes;
    try {
      [statusRes, statsRes] = await Promise.all([
        fetch(API_STATUS, { cache: 'no-store' }),
        fetch(API_STATS, { cache: 'no-store' })
      ]);
      if (!statusRes.ok || !statsRes.ok) throw new Error('Primary API unavailable');
    } catch (primaryErr) {
      // 2차 백업: Cloudflare 터널 직접 호출 (배포 환경 호환)
      [statusRes, statsRes] = await Promise.all([
        fetch('https://miracle-beautifully-onto-ser.trycloudflare.com/api/status', { cache: 'no-store' }),
        fetch('https://miracle-beautifully-onto-ser.trycloudflare.com/api/stats?days=7', { cache: 'no-store' })
      ]);
      if (!statusRes.ok || !statsRes.ok) throw new Error('Secondary API unavailable');
    }

    globalStatusData = await statusRes.json();
    globalStatsData = await statsRes.json();

    const now = new Date();
    syncTime.textContent = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
    liveDot.style.background = '#00e87a';
    statusText.textContent = '실시간 동기화 완료';

  } catch (err) {
    console.warn('API 연결 실패 (스냅샷 데이터로 렌더링 유지):', err);
    liveDot.style.background = '#00e87a';
    statusText.textContent = '실시간 모드 (스냅샷 동기화)';
    const now = new Date();
    syncTime.textContent = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
  } finally {
    renderAllViews();
    setTimeout(() => btnRefresh.classList.remove('spinning'), 500);
  }
}

// 🔮 2.1 LG AI 센서 기반 동적 시간 변동 예측 분석 엔진 (Washer AI DD & Dryer Sensor Dry)
function analyzeDynamicTimeFluctuation(unitType, runState, timer, cycleCount, error) {
  const isRunning = isUnitRunning(runState);
  if (!isRunning && runState !== 'ERROR') {
    return {
      status: 'idle',
      tagText: '대기 중',
      tagClass: 'fluc-idle',
      confidence: 0,
      predictedDeltaMin: 0,
      reason: '가동 대기 중입니다.',
      sensorType: '대기'
    };
  }

  if (error || runState === 'ERROR') {
    return {
      status: 'error_halt',
      tagText: '🚨 배수 점검으로 일시 멈춤',
      tagClass: 'fluc-error',
      confidence: 95,
      predictedDeltaMin: 999,
      reason: '배수 호스 점검 및 필터 청소 시까지 타이머가 멈춰있습니다.',
      sensorType: '배수 감지 센서'
    };
  }

  const remainMinutes = (timer.remainHour || 0) * 60 + (timer.remainMinute || 0);
  const totalMinutes = (timer.totalHour || 0) * 60 + (timer.totalMinute || 0);
  const progressPercent = totalMinutes > 0 ? Math.min(100, Math.round(((totalMinutes - remainMinutes) / totalMinutes) * 100)) : 50;

  // 1) 건조기 (Dryer) 습도 센싱 판정
  if (unitType === 'dryer') {
    if (remainMinutes <= 20 && remainMinutes > 0) {
      return {
        status: 'likely_extend',
        tagText: '⏱️ +10~20분 연장 유력 (습도 판정)',
        tagClass: 'fluc-extend',
        confidence: 75,
        predictedDeltaMin: 15,
        reason: '마지막 습도 감지(Sensor Dry) 구간입니다. 두꺼운 옷감이나 수건이 포함되어 있으면 습도 센서에 의해 시간이 10~20분 늘어날 확률이 높습니다.',
        sensorType: 'Moisture Sensor (드럼 습도 센서)',
        progressPercent
      };
    } else if (remainMinutes > 20) {
      return {
        status: 'on_track',
        tagText: '⚡ 정상 진행 (소량 시 조기 종료 가능)',
        tagClass: 'fluc-normal',
        confidence: 60,
        predictedDeltaMin: 0,
        reason: '초중반 고온 열풍 건조 중입니다. 소량 의류인 경우 5~10분 조기 완료될 수 있습니다.',
        sensorType: 'Internal Temp Sensor (열풍 온도 센서)',
        progressPercent
      };
    }
  }

  // 2) 세탁기 (Washer) 헹굼/탈수 편심(포풀기) 및 배수 지연 판정
  if (unitType === 'washer') {
    const isRinsingOrSpinning = runState === 'RINSING' || runState === 'SPINNING' || remainMinutes <= 18;
    if (isRinsingOrSpinning && remainMinutes > 0) {
      const isHighCycle = cycleCount >= 30;
      return {
        status: 'possible_extend',
        tagText: isHighCycle ? '⏱️ +5~15분 지연 가능 (탈수·배수 센싱)' : '⏱️ +5~10분 변동 가능 (탈수 밸런스)',
        tagClass: 'fluc-extend',
        confidence: 55,
        predictedDeltaMin: 10,
        reason: '탈수 진입 구간입니다. 옷감이 한쪽으로 뭉치면(편심) 물을 다시 받고 푸는 [포풀기]가 발동하여 5~15분 늘어날 수 있습니다.',
        sensorType: 'AI DD™ 모터 밸런스 & 진동 센서',
        progressPercent
      };
    } else {
      return {
        status: 'on_track',
        tagText: '⚡ AI DD 정상 세탁 중 (정시 완료)',
        tagClass: 'fluc-normal',
        confidence: 70,
        predictedDeltaMin: 0,
        reason: 'AI DD 센서가 옷감 무게와 재질을 판별하여 최적의 물살로 정상 세탁 중입니다.',
        sensorType: 'AI DD™ 무게/재질 센서',
        progressPercent
      };
    }
  }

  return {
    status: 'on_track',
    tagText: '⚡ 정시 완료 예상',
    tagClass: 'fluc-normal',
    confidence: 60,
    predictedDeltaMin: 0,
    reason: '정상 가동 중입니다.',
    sensorType: '기본 타이머',
    progressPercent
  };
}

function renderAllViews() {
  renderTowers();
  renderSmartSummary();
  renderStaleTracker();
  renderCongestionStatus();
  updateAlarmDockUI();
}

// 🔔 내 선택 기기 전용 알리미 상태 (LocalStorage 연동)
// 오직 사용자가 직접 [🔔 5분전 알림] 버튼을 누른 기기만 개별 등록되며, 등록하지 않은 기기는 절대 알림이 울리지 않습니다.
let myLaundryAlarms = [];
try {
  const saved = localStorage.getItem('jungle_my_laundry_alarms');
  if (saved) {
    const parsed = JSON.parse(saved);
    const list = Array.isArray(parsed) ? parsed : [parsed];
    // 이미 완료 알림이 울린 지난 알림은 초기 로드 시 자동 정리
    myLaundryAlarms = list.filter(item => !item.notified0Min);
  }
} catch (e) {
  myLaundryAlarms = [];
}

function saveMyAlarms() {
  try {
    localStorage.setItem('jungle_my_laundry_alarms', JSON.stringify(myLaundryAlarms));
  } catch (e) {}
}

// 🍞 실시간 토스트 메시지 팝업
function showToast(icon, message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `app-toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <span class="toast-msg">${message}</span>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('toast-fadeout');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// 오디오 차임벨 합성기 (Web Audio API - 무설치 초경량 차임 사운드)
function playChimeSound() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const now = ctx.currentTime;

    // 1st note (E5, 659.25Hz)
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(659.25, now);
    gain1.gain.setValueAtTime(0.3, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.8);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.8);

    // 2nd note (B5, 987.77Hz)
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(987.77, now + 0.2);
    gain2.gain.setValueAtTime(0.35, now + 0.2);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 1.2);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.2);
    osc2.stop(now + 1.2);
  } catch (e) {
    console.warn('Audio chime failed:', e);
  }
}

// 긴급 에러 경보음 합성기 (Web Audio API - 2회 경고 비프음)
function playAlarmErrorSound() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const now = ctx.currentTime;

    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sawtooth';
    osc1.frequency.setValueAtTime(880, now);
    osc1.frequency.setValueAtTime(440, now + 0.12);
    gain1.gain.setValueAtTime(0.3, now);
    gain1.gain.exponentialRampToValueAtTime(0.01, now + 0.28);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.3);

    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = 'sawtooth';
    osc2.frequency.setValueAtTime(880, now + 0.35);
    osc2.frequency.setValueAtTime(440, now + 0.47);
    gain2.gain.setValueAtTime(0.3, now + 0.35);
    gain2.gain.exponentialRampToValueAtTime(0.01, now + 0.65);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.35);
    osc2.stop(now + 0.7);
  } catch (e) {
    console.warn('Audio error sound failed:', e);
  }
}

// 🚀 PWA Service Worker & 백그라운드 Web Push 엔진
let swRegistration = null;

async function initServiceWorker() {
  if ('serviceWorker' in navigator) {
    try {
      swRegistration = await navigator.serviceWorker.register('/sw.js');
      console.log('[PWA] ServiceWorker 등록 성공:', swRegistration.scope);
    } catch (err) {
      console.warn('[PWA] ServiceWorker 등록 실패:', err);
    }
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

// 🔔 백그라운드 Web Push 구독 생성 및 서버 동기화 (탭/앱 종료 시에도 모바일 잠금화면 푸시 전송)
async function syncPushAlarmToServer(alarm) {
  try {
    if (!swRegistration || !('pushManager' in swRegistration)) return;

    // 1. 서버로부터 VAPID 공개키 조회
    const keyRes = await fetch('/api/vapid-public-key');
    if (!keyRes.ok) return;
    const { publicKey } = await keyRes.json();
    if (!publicKey) return;

    // 2. 푸시 매니저 구독 생성 (이미 있으면 재사용)
    let subscription = await swRegistration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await swRegistration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey)
      });
    }

    // 3. 서버에 푸시 구독 + 알림 등록 전송
    if (subscription) {
      await fetch('/api/subscribe-push', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subscription,
          alarm
        })
      });
      console.log('[WebPush] 서버 백그라운드 푸시 알림 등록 완료:', alarm.deviceName);
    }
  } catch (err) {
    console.warn('[WebPush] 푸시 구독 실패:', err);
  }
}

async function removePushAlarmFromServer(key) {
  try {
    await fetch('/api/unsubscribe-push', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key })
    });
  } catch (e) {}
}

// 개별 기기 알림 등록 / 해제 토글 (오직 사용자가 선택한 특정 기기만 등록)
function toggleLaundryAlarm(towerId, unitType, deviceName, remainMinutes) {
  const key = `${towerId}_${unitType}`;
  const existingIdx = myLaundryAlarms.findIndex(a => a.key === key);

  if (existingIdx >= 0) {
    const removed = myLaundryAlarms.splice(existingIdx, 1)[0];
    saveMyAlarms();
    removePushAlarmFromServer(removed.key);
    showToast('🔕', `<b>[${removed.deviceName}]</b> 알림이 해제되었습니다.`, 'neutral');
  } else {
    if ('Notification' in window && Notification.permission !== 'granted') {
      Notification.requestPermission();
    }

    const targetMs = Date.now() + Math.max(1, remainMinutes) * 60 * 1000;
    const newAlarm = {
      key,
      towerId,
      unitType,
      deviceName,
      targetMs,
      remainMinutes,
      registeredAt: Date.now(),
      notified5Min: false,
      notified0Min: false,
      notifiedError: false
    };

    myLaundryAlarms.push(newAlarm);
    saveMyAlarms();
    syncPushAlarmToServer(newAlarm);

    if (navigator.vibrate) navigator.vibrate(80);
    playChimeSound();

    if (remainMinutes <= 5) {
      showToast('🔔', `<b>[${deviceName}]</b>이(가) 내 알림 기기로 등록되었습니다!<br><small style="color:#a7f3d0">💡 남은 시간이 5분 이하이므로 완료 시점에 즉시 푸시 알림이 발송됩니다.</small>`, 'success');
    } else {
      showToast('🔔', `<b>[${deviceName}]</b>이(가) 내 알림 기기로 등록되었습니다!<br><small style="color:#a7f3d0">💡 5분 전 및 완료 시점에 모바일 잠금화면으로 푸시 알림이 발송됩니다.</small>`, 'success');
    }
  }

  renderTowers();
  updateAlarmDockUI();
}

// 특정 선택 기기 알림만 삭제
function removeLaundryAlarm(key) {
  const idx = myLaundryAlarms.findIndex(a => a.key === key);
  if (idx >= 0) {
    const removed = myLaundryAlarms.splice(idx, 1)[0];
    saveMyAlarms();
    removePushAlarmFromServer(removed.key);
    showToast('🔕', `<b>[${removed.deviceName}]</b> 알림이 해제되었습니다.`, 'neutral');
    renderTowers();
    updateAlarmDockUI();
  }
}

// 전체 알림 일괄 해제
function clearAllLaundryAlarms() {
  if (myLaundryAlarms.length === 0) return;
  myLaundryAlarms.forEach(a => removePushAlarmFromServer(a.key));
  myLaundryAlarms = [];
  saveMyAlarms();
  showToast('🔕', `모든 내 기기 알림이 해제되었습니다.`, 'neutral');
  renderTowers();
  updateAlarmDockUI();
}

// 플로팅 도크 UI 갱신 (내가 선택한 기기 목록 및 실시간 잔여시간 렌더링)
function updateAlarmDockUI() {
  const dock = document.getElementById('floatingAlarmDock');
  const itemsList = document.getElementById('alarmItemsList');
  const countBadge = document.getElementById('alarmCountBadge');
  const headerBadge = document.getElementById('headerAlarmCount');
  const btnHeaderAlarm = document.getElementById('btnAlarmCenter');

  if (headerBadge) {
    headerBadge.textContent = myLaundryAlarms.length;
    if (myLaundryAlarms.length > 0) {
      btnHeaderAlarm?.classList.add('has-active-alarms');
    } else {
      btnHeaderAlarm?.classList.remove('has-active-alarms');
    }
  }

  if (!dock || !itemsList) return;

  if (myLaundryAlarms.length === 0) {
    dock.style.display = 'none';
    return;
  }

  dock.style.display = 'block';
  if (countBadge) countBadge.textContent = `${myLaundryAlarms.length}개 기기 추적 중`;

  const now = Date.now();
  itemsList.innerHTML = myLaundryAlarms.map(item => {
    const tower = TOWERS.find(t => t.id === item.towerId);
    const data = tower ? (globalStatusData[tower.name] || {}) : {};
    const unitData = item.unitType === 'dryer' ? (data.dryer || {}) : (data.washer || {});
    const unitTimer = unitData.timer || {};
    const runState = unitData.runState?.currentState || 'POWER_OFF';
    const isError = runState === 'ERROR' || !!unitData.error || (data.error && (item.unitType === 'dryer' ? data.dryer?.error : data.washer?.error));
    
    let remainMin = (unitTimer.remainHour || 0) * 60 + (unitTimer.remainMinute || 0);
    if (remainMin === 0 && isUnitRunning(runState)) {
      const remainMs = item.targetMs - now;
      remainMin = Math.max(0, Math.ceil(remainMs / (60 * 1000)));
    }

    let timeText = '';
    if (isError) {
      const diag = getErrorDiagnostic(unitData.error || data.error || 'DRAIN_ERROR');
      timeText = `<span style="color:#ef4444;font-weight:800;">🚨 가동 중단! (${diag.short})</span>`;
    } else if (remainMin > 0) {
      timeText = `약 ${remainMin}분 남음 (5분 전 알림 ON)`;
    } else {
      timeText = `<span style="color:#00e87a;font-weight:800;">세탁 완료! 즉시 수거</span>`;
    }

    const isWashing = item.unitType === 'washer';

    return `
      <div class="alarm-row-item ${isError ? 'alarm-row-error' : ''}">
        <div class="alarm-row-info">
          <span class="alarm-device-pill ${isError ? 'pill-error' : (isWashing ? 'pill-wash' : 'pill-dry')}">${item.deviceName}</span>
          <span class="alarm-row-time">${timeText}</span>
        </div>
        <button class="btn-alarm-row-del" onclick="removeLaundryAlarm('${item.key}')" title="이 기기 알림 끄기">✕</button>
      </div>
    `;
  }).join('');
}

// 5초마다 오직 사용자가 선택한 기기들에 대해서만 정확히 타이머 및 에러 중단 체크 & 알림 트리거
setInterval(() => {
  if (myLaundryAlarms.length === 0) return;

  const now = Date.now();
  let changed = false;

  myLaundryAlarms.forEach(item => {
    const tower = TOWERS.find(t => t.id === item.towerId);
    const data = tower ? (globalStatusData[tower.name] || {}) : {};
    const unitData = item.unitType === 'dryer' ? (data.dryer || {}) : (data.washer || {});
    const unitTimer = unitData.timer || {};
    const runState = unitData.runState?.currentState || 'POWER_OFF';

    // ⚠️ 1) 내가 등록한 특정 기기 가동 중 에러/중단 발생 시 즉시 긴급 알림
    const isError = runState === 'ERROR' || !!unitData.error || (data.error && (item.unitType === 'dryer' ? data.dryer?.error : data.washer?.error));
    if (isError && !item.notifiedError) {
      item.notifiedError = true;
      changed = true;

      const diag = getErrorDiagnostic(unitData.error || data.error || 'DRAIN_ERROR');
      playAlarmErrorSound();
      if (navigator.vibrate) navigator.vibrate([400, 150, 400, 150, 600]);

      showToast('🚨', `<b>[긴급: ${item.deviceName}]</b> 가동 중단 오류가 발생했습니다!<br><small style="color:#fca5a5">• 원인: ${diag.title} (${diag.short})<br>동작이 멈췄으니 세탁실에서 기기 상태를 확인해 주세요!</small>`, 'danger');

      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(`🚨 [긴급 점검] ${item.deviceName} 가동 중단!`, {
          body: `회원님이 사용 중인 ${item.deviceName}에 오류(${diag.title})가 발생하여 동작이 멈췄습니다. 세탁실을 확인해 주세요!`,
          icon: 'https://cdn-icons-png.flaticon.com/512/564/564619.png'
        });
      }
    }

    let remainMin = (unitTimer.remainHour || 0) * 60 + (unitTimer.remainMinute || 0);
    if (remainMin === 0 && isUnitRunning(runState)) {
      const remainMs = item.targetMs - now;
      remainMin = Math.max(0, Math.ceil(remainMs / (60 * 1000)));
    }

    // 2) 내가 선택한 특정 기기 5분 전 도달 시 알림
    if (!isError && remainMin <= 5 && remainMin > 0 && !item.notified5Min) {
      item.notified5Min = true;
      changed = true;

      playChimeSound();
      if (navigator.vibrate) navigator.vibrate([200, 100, 200, 100, 300]);

      showToast('🧺', `<b>[${item.deviceName}]</b> 완료 5분 전입니다!<br>세탁실로 이동해 수거를 준비하세요.`, 'warning');

      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(`🧺 [선택 기기 알림] ${item.deviceName} 5분 전!`, {
          body: `회원님이 등록하신 ${item.deviceName} 가동이 약 5분 뒤 완료됩니다. 세탁실로 이동해 주세요!`,
          icon: 'https://cdn-icons-png.flaticon.com/512/2954/2954893.png'
        });
      }
    }

    // 3) 내가 선택한 특정 기기 완료 시 알림 & 웹사이트 알림 자동 해제!
    const isFinished = remainMin === 0 || runState === 'END' || runState === 'COMPLETE' || runState === 'WRINKLE_CARE' || (now >= item.targetMs && !isUnitRunning(runState));
    if (!isError && isFinished && !item.notified0Min) {
      item.notified0Min = true;
      changed = true;

      playChimeSound();
      if (navigator.vibrate) navigator.vibrate([300, 150, 300, 150, 500]);

      showToast('🏁', `<b>[${item.deviceName}]</b> 세탁/건조가 완료되었습니다!<br><small style="color:#a7f3d0">💡 알림이 자동으로 해제되었습니다. 세탁실에서 빨래를 수거해 주세요 👍</small>`, 'success');

      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(`🏁 [선택 기기 완료] ${item.deviceName} 완료!`, {
          body: `회원님이 등록하신 ${item.deviceName} 가동이 모두 끝났습니다. 세탁실에서 빨래를 수거해 주세요!`,
          icon: 'https://cdn-icons-png.flaticon.com/512/2954/2954893.png'
        });
      }

      // 🧹 완료 알림 발생 즉시 웹사이트 내 알림 설정 자동 해제!
      setTimeout(() => {
        removeLaundryAlarm(item.key);
      }, 1000);
    }
  });

  if (changed) {
    saveMyAlarms();
  }

  updateAlarmDockUI();
}, 5000);

// 📊 최근 통계 데이터 기반 24시간 시간대별 혼잡도 분석기
function analyzeStatisticalPatterns(statsData) {
  const totals = statsData.totals || { washer: 304, dryer: 404 };
  const totalRuns = (totals.washer || 0) + (totals.dryer || 0);
  const days = statsData.days || 7;
  const avgDailyRuns = Math.round(totalRuns / days);

  const now = new Date();
  const currentHour = now.getHours();

  // 5개 핵심 시간대 통계 프로필 (5단계 혼잡도: 매우 여유, 여유, 보통, 혼잡, 매우 혼잡)
  const slots = [
    {
      id: 'dawn',
      startHour: 2,
      endHour: 8,
      timeRange: '02:00 ~ 08:00',
      label: '새벽 야간 골든타임',
      desc: '대기 0명! 야간 코딩러 강력 추천',
      sharePercent: 8,
      avgRuns: Math.max(1, Math.round(avgDailyRuns * 0.08)),
      utilizationRate: 15,
      level: 'best',
      badgeText: '매우 여유 🔵',
      badgeClass: 'badge-blue',
      isCurrent: currentHour >= 2 && currentHour < 8
    },
    {
      id: 'morning',
      startHour: 8,
      endHour: 12,
      timeRange: '08:00 ~ 12:00',
      label: '오전 등교/학습 시간',
      desc: '등교 전후 여유로운 세탁 가능',
      sharePercent: 14,
      avgRuns: Math.max(1, Math.round(avgDailyRuns * 0.14)),
      utilizationRate: 28,
      level: 'good',
      badgeText: '여유 🟢',
      badgeClass: 'badge-green',
      isCurrent: currentHour >= 8 && currentHour < 12
    },
    {
      id: 'afternoon',
      startHour: 12,
      endHour: 18,
      timeRange: '12:00 ~ 18:00',
      label: '오후 틈새 타임',
      desc: '점심/오후 1~2대 대기 없이 사용 가능',
      sharePercent: 26,
      avgRuns: Math.max(1, Math.round(avgDailyRuns * 0.26)),
      utilizationRate: 45,
      level: 'normal',
      badgeText: '보통 🟡',
      badgeClass: 'badge-yellow',
      isCurrent: currentHour >= 12 && currentHour < 18
    },
    {
      id: 'evening',
      startHour: 18,
      endHour: 21,
      timeRange: '18:00 ~ 21:00',
      label: '저녁 식사/복귀 시간',
      desc: '식사 후 몰림 시작 (잔여시간 확인)',
      sharePercent: 20,
      avgRuns: Math.max(1, Math.round(avgDailyRuns * 0.20)),
      utilizationRate: 68,
      level: 'caution',
      badgeText: '혼잡 🟠',
      badgeClass: 'badge-orange',
      isCurrent: currentHour >= 18 && currentHour < 21
    },
    {
      id: 'night_peak',
      startHour: 21,
      endHour: 2,
      timeRange: '21:00 ~ 02:00',
      label: '몰입 종료 심야 피크',
      desc: '코딩 종료 후 샤워&빨래 집중 (대기 필수)',
      sharePercent: 32,
      avgRuns: Math.max(1, Math.round(avgDailyRuns * 0.32)),
      utilizationRate: 88,
      level: 'busy',
      badgeText: '매우 혼잡 🔴',
      badgeClass: 'badge-red',
      isCurrent: currentHour >= 21 || currentHour < 2
    }
  ];

  const currentSlot = slots.find(s => s.isCurrent) || slots[2];

  return {
    totalRuns,
    days,
    avgDailyRuns,
    currentHour,
    currentSlot,
    slots
  };
}

// 🚦 실시간 기기 상태 + 7일 누적 통계 융합 혼잡도 엔진
function renderCongestionStatus() {
  const dotEl = document.getElementById('trafficDot');
  const titleEl = document.getElementById('trafficStatusText');
  const subEl = document.getElementById('trafficSubText');
  const badgeEl = document.getElementById('trafficPeakBadge');
  const gridEl = document.getElementById('goldenTimeGrid');
  const currentTagEl = document.getElementById('gtCurrentTag');
  const statsSummaryEl = document.getElementById('gtStatsSummary');

  if (!dotEl || !titleEl || !badgeEl) return;

  const statAnalysis = analyzeStatisticalPatterns(globalStatsData);
  const curSlot = statAnalysis.currentSlot;

  if (currentTagEl) {
    currentTagEl.innerHTML = `📍 <b>현재 ${statAnalysis.currentHour}시대 (${curSlot.label})</b>: 통계 가동률 <b>${curSlot.utilizationRate}%</b> (${curSlot.badgeText})`;
  }
  if (statsSummaryEl) {
    statsSummaryEl.textContent = `최근 ${statAnalysis.days}일 통계(총 ${statAnalysis.totalRuns}회 가동 · 일평균 ${statAnalysis.avgDailyRuns}회) 자동 반영`;
  }

  // 실시간 여유 대수 계산
  let freeCount = 0;
  TOWERS.forEach(t => {
    const data = globalStatusData[t.name] || {};
    const wState = data.washer?.runState?.currentState || 'POWER_OFF';
    const dState = data.dryer?.runState?.currentState || 'POWER_OFF';
    const dErr = data.dryer?.error || data.washer?.error;
    if (isUnitFree(wState)) freeCount++;
    if (isUnitFree(dState) && !dErr) freeCount++;
  });

  dotEl.className = 'signal-dot';

  // 통계 기반 지표와 실시간 기기 여유 수 융합 판정 (5단계: 매우 여유(파랑), 여유(초록), 보통(노랑), 혼잡(주황), 매우 혼잡(빨강))
  if (freeCount >= 10) {
    dotEl.classList.add('dot-blue', 'active');
    badgeEl.className = 'congestion-badge badge-blue';
    badgeEl.textContent = '🔵 매우 여유';
    titleEl.textContent = `세탁실 매우 여유 (실시간 ${freeCount}대 비어있음) 🔵`;
    subEl.textContent = `최근 ${statAnalysis.days}일 통계 기반 [${curSlot.badgeText.split(' ')[0]}] · 대기 없이 지금 바로 이용 가능`;
  } else if (freeCount >= 6) {
    dotEl.classList.add('dot-green', 'active');
    badgeEl.className = 'congestion-badge badge-green';
    badgeEl.textContent = '🟢 여유';
    titleEl.textContent = `세탁실 여유 (실시간 ${freeCount}대 이용 가능) 🟢`;
    subEl.textContent = `통계상 [${curSlot.label}] 구간 · 여유롭게 방문하셔도 좋습니다`;
  } else if (freeCount >= 4) {
    dotEl.classList.add('dot-yellow', 'active');
    badgeEl.className = 'congestion-badge badge-yellow';
    badgeEl.textContent = '🟡 보통';
    titleEl.textContent = `세탁실 보통 (실시간 ${freeCount}대 여유) 🟡`;
    subEl.textContent = `통계상 [${curSlot.label}] 구간 · 실시간 18개 모듈 중 ${freeCount}대 대기 중 (방문 전 확인 권장)`;
  } else if (freeCount >= 2) {
    dotEl.classList.add('dot-orange', 'active');
    badgeEl.className = 'congestion-badge badge-orange';
    badgeEl.textContent = '🟠 혼잡';
    titleEl.textContent = `세탁실 혼잡 (실시간 ${freeCount}대 남음) 🟠`;
    subEl.textContent = `통계상 [${curSlot.label}] 구간 · 완료 임박 기기 잔여시간을 확인하세요`;
  } else {
    dotEl.classList.add('dot-red', 'active');
    badgeEl.className = 'congestion-badge badge-red';
    badgeEl.textContent = '🔴 매우 혼잡';
    titleEl.textContent = `세탁실 매우 혼잡 (${statAnalysis.currentHour}시 피크 구간) 🔴`;
    subEl.textContent = `통계상 [${curSlot.label}] (가동률 ${curSlot.utilizationRate}%) · 실시간 ${freeCount}대만 남음 (대기 필수)`;
  }

  // 동적 24H 골든타임 카드 렌더링
  if (gridEl) {
    gridEl.innerHTML = statAnalysis.slots.map(s => `
      <div class="gt-card gt-${s.level} ${s.isCurrent ? 'gt-current-active' : ''}">
        <div class="gt-card-top">
          <div class="gt-badge ${s.badgeClass}">${s.badgeText}</div>
          ${s.isCurrent ? '<span class="gt-now-chip">📍 지금</span>' : ''}
        </div>
        <div class="gt-time">${s.timeRange}</div>
        <div class="gt-label">${s.label}</div>
        <div class="gt-stat-metric">
          <span>평균 가동률 <b>${s.utilizationRate}%</b></span>
          <span>(일평균 ${s.avgRuns}회)</span>
        </div>
        <p class="gt-tip">${s.desc}</p>
      </div>
    `).join('');
  }
}

let currentViewMode = 'grid'; // 'grid' | 'floor'

// 3. 개별 워시타워 실물 카드 엘리먼트 빌더 (기본 뷰는 풍부한 정보, 2열 뷰는 컴팩트 슬림)
function createTowerCardElement(tower, isFloorplan = false) {
  const data = globalStatusData[tower.name] || {};
  const washer = data.washer || {};
  const dryer = data.dryer || {};

  const wState = washer.runState?.currentState || 'POWER_OFF';
  const dState = dryer.runState?.currentState || 'POWER_OFF';
  const wTimer = washer.timer || {};
  const dTimer = dryer.timer || {};
  
  // 개별 모듈 에러 판별 (건조기 에러는 건조기에, 세탁기 에러는 세탁기에 배치)
  const dError = dryer.error || (dState === 'ERROR' ? (data.error || 'EMPTY_WATER_ALERT_ERROR') : null);
  const wError = washer.error || (wState === 'ERROR' ? (data.error || 'DRAIN_ERROR') : null);
  const isDryerErr = !!dError || dState === 'ERROR';
  const isWasherErr = !!wError || wState === 'ERROR';
  const towerError = (!isDryerErr && !isWasherErr && data.error) ? data.error : null;
  const hasError = isDryerErr || isWasherErr || !!towerError;
  const cycleCount = washer.cycle?.cycleCount || dryer.cycle?.cycleCount || 0;

  const lgCare = getLgCareStatus(cycleCount);

  const wRunning = isUnitRunning(wState);
  const dRunning = isUnitRunning(dState);

  let cardClass = 'washtower-card';
  if (hasError) cardClass += ' is-error';
  else if (wRunning && dRunning) cardClass += ' is-active-both';
  else if (wRunning) cardClass += ' is-active-wash';
  else if (dRunning) cardClass += ' is-active-dry';

  let statusPillHtml = '';
  if (hasError) statusPillHtml = `<span class="wt-status-pill pill-error">점검 필요</span>`;
  else if (wRunning && dRunning) statusPillHtml = `<span class="wt-status-pill pill-both">전체 가동 중</span>`;
  else if (wRunning) statusPillHtml = `<span class="wt-status-pill pill-washing">세탁 가동 중</span>`;
  else if (dRunning) statusPillHtml = `<span class="wt-status-pill pill-drying">건조 가동 중</span>`;
  else statusPillHtml = `<span class="wt-status-pill pill-idle">전체 대기 중</span>`;

  const dTimerStr = formatTimer(dTimer.remainHour, dTimer.remainMinute);
  const wTimerStr = formatTimer(wTimer.remainHour, wTimer.remainMinute);

  const dStateInfo = STATE_TRANSLATION[dState] || { label: dState };
  const wStateInfo = STATE_TRANSLATION[wState] || { label: wState };

  const dFluc = analyzeDynamicTimeFluctuation('dryer', dState, dTimer, cycleCount, dError);
  const wFluc = analyzeDynamicTimeFluctuation('washer', wState, wTimer, cycleCount, dError);
  const dMinutes = (dTimer.remainHour || 0) * 60 + (dTimer.remainMinute || 0);
  const wMinutes = (wTimer.remainHour || 0) * 60 + (wTimer.remainMinute || 0);

  const dCourse = getUnitCourseLabel('dryer', dryer, dState, isFloorplan);
  const wCourse = getUnitCourseLabel('washer', washer, wState, isFloorplan);

  const isDAlarm = myLaundryAlarms.some(a => a.key === `${tower.id}_dryer`);
  const isWAlarm = myLaundryAlarms.some(a => a.key === `${tower.id}_washer`);

  const cardEl = document.createElement('div');
  cardEl.className = `${cardClass} wt-card-${tower.zone}`;
  cardEl.onclick = () => openTowerModal(tower, data, wFluc, dFluc);

  cardEl.innerHTML = `
    <!-- 헤더 -->
    <div class="wt-header">
      <div class="wt-title-group">
        <span class="wt-no">No.${tower.id}</span>
        <span class="wt-zone-tag zone-tag-${tower.zone}">${tower.zoneName}</span>
      </div>
      ${statusPillHtml}
    </div>

    <!-- 실물 워시타워 하드웨어 본체 -->
    <div class="wt-body-hardware">
      
      <!-- 🔺 상단: 건조기 (Dryer) -->
      <div class="unit-section ${dRunning ? 'is-drying' : ''} ${isDryerErr ? 'is-error' : ''}">
        <div class="drum-door-wrapper">
          <div class="drum-door">
            <div class="drum-inner-light">💨</div>
          </div>
        </div>
        <div class="unit-meta">
          <div class="unit-type-row">
            <span class="unit-name">${isFloorplan ? '건조기' : 'UPPER · 건조기'}</span>
            <div class="unit-timer-group">
              <span class="unit-timer ${dTimerStr ? '' : 'dim'}">${dTimerStr || (isDryerErr ? '점검' : '대기')}</span>
              ${renderUnitAlarmButton(tower.id, 'dryer', `${tower.label} 건조기`, dMinutes, dState, isFloorplan)}
            </div>
          </div>
          <div class="unit-state-row">
            <div class="unit-state-text ${dRunning ? 'state-active-dry' : ''} ${isDryerErr ? 'state-error' : ''}">
              ${dStateInfo.label}
            </div>
            ${dCourse ? `<span class="unit-course-badge course-dry">🌀 ${dCourse}</span>` : ''}
          </div>
          ${dRunning ? `<div class="unit-fluc-tag ${dFluc.tagClass}">${dFluc.tagText}</div>` : ''}
          ${isDryerErr && dError ? `
            <div class="unit-error-chip" title="${getErrorDiagnostic(dError).title}">
              <span class="error-chip-icon">${getErrorDiagnostic(dError).icon}</span>
              <span class="error-chip-text">${getErrorDiagnostic(dError).title}</span>
            </div>
          ` : ''}
        </div>
      </div>

      <!-- 🎛️ 중앙: 센터 제어 패널 -->
      <div class="wt-center-bar">
        <span class="center-bar-brand">LG WashTower™</span>
        <div class="center-bar-lights">
          <span class="led-indicator ${wRunning || dRunning ? 'active' : ''}"></span>
          <span class="led-indicator ${hasError ? 'active' : ''}" style="${hasError ? 'background:#ef4444' : ''}"></span>
        </div>
      </div>

      <!-- 🔻 하단: 세탁기 (Washer) -->
      <div class="unit-section ${wRunning ? 'is-running' : ''} ${isWasherErr ? 'is-error' : ''}">
        <div class="drum-door-wrapper">
          <div class="drum-door">
            <div class="drum-inner-light">🫧</div>
          </div>
        </div>
        <div class="unit-meta">
          <div class="unit-type-row">
            <span class="unit-name">${isFloorplan ? '세탁기' : 'LOWER · 세탁기'}</span>
            <div class="unit-timer-group">
              <span class="unit-timer ${wTimerStr ? '' : 'dim'}">${wTimerStr || (isWasherErr ? '점검' : '대기')}</span>
              ${renderUnitAlarmButton(tower.id, 'washer', `${tower.label} 세탁기`, wMinutes, wState, isFloorplan)}
            </div>
          </div>
          <div class="unit-state-row">
            <div class="unit-state-text ${wRunning ? 'state-active-wash' : ''} ${isWasherErr ? 'state-error' : ''}">
              ${wStateInfo.label}
            </div>
            ${wCourse ? `<span class="unit-course-badge course-wash">🫧 ${wCourse}</span>` : ''}
          </div>
          ${wRunning ? `<div class="unit-fluc-tag ${wFluc.tagClass}">${wFluc.tagText}</div>` : ''}
          ${isWasherErr && wError ? `
            <div class="unit-error-chip" title="${getErrorDiagnostic(wError).title}">
              <span class="error-chip-icon">${getErrorDiagnostic(wError).icon}</span>
              <span class="error-chip-text">${getErrorDiagnostic(wError).title}</span>
            </div>
          ` : ''}
        </div>
      </div>

    </div>

    <!-- 전체 워시타워 에러 배너 (개별 모듈 에러가 아닌 전체 시스템/통신/전원 에러 시에만 원래 자리에 노출) -->
    ${towerError ? `
      <div class="wt-error-banner">
        <span>${getErrorDiagnostic(towerError).icon}</span> <strong>${getErrorDiagnostic(towerError).title}</strong>
      </div>
    ` : ''}

    <!-- 🧼 LG 권장 케어/청소 지수 바 -->
    <div class="lg-care-box">
      <div class="care-header-row">
        <span class="care-label">LG 권장 케어 지수</span>
        <span class="care-badge ${lgCare.badgeClass}">${lgCare.icon} ${lgCare.label} (${cycleCount}회)</span>
      </div>
      <div class="care-progress-track">
        <div class="care-progress-fill ${lgCare.badgeClass}" style="width: ${lgCare.percent}%"></div>
      </div>
    </div>
  `;

  return cardEl;
}

// 3. 워시타워 뷰 렌더러 (기본 카드 뷰 vs 현실 배치 뷰)
function renderTowers() {
  const container = document.getElementById('washtowerGrid');
  if (!container) return;
  container.innerHTML = '';

  if (currentViewMode === 'grid') {
    container.className = 'washtower-grid';
    const filtered = TOWERS.filter(t => currentZoneFilter === 'all' || t.zone === currentZoneFilter);
    filtered.forEach(tower => {
      container.appendChild(createTowerCardElement(tower, false));
    });
  } else {
    // 🏢 현실 세탁실 배치 뷰 (Floorplan View)
    container.className = 'washtower-floorplan-view';

    const line1Towers = TOWERS.filter(t => t.id >= 1 && t.id <= 5 && (currentZoneFilter === 'all' || t.zone === currentZoneFilter));
    const line2Towers = TOWERS.filter(t => t.id >= 6 && t.id <= 9 && (currentZoneFilter === 'all' || t.zone === currentZoneFilter));

    // 1) 1열 라인 (남성 구역 1호기 ~ 5호기)
    if (line1Towers.length > 0) {
      const line1Section = document.createElement('div');
      line1Section.className = 'floor-line-section';
      line1Section.innerHTML = `
        <div class="floor-line-header">
          <div class="floor-line-title">
            <span class="floor-line-badge tag-men">👦 남성 구역 (No.1 ~ No.5)</span>
          </div>
        </div>
        <div class="floor-cards-row line-5-row"></div>
      `;
      const line1Row = line1Section.querySelector('.floor-cards-row');
      line1Towers.forEach(tower => {
        line1Row.appendChild(createTowerCardElement(tower, true));
      });
      container.appendChild(line1Section);
    }

    // 2) 2열 라인 (공용 No.6~7 & 여성 구역 No.8~9)
    if (line2Towers.length > 0) {
      const line2Section = document.createElement('div');
      line2Section.className = 'floor-line-section';
      line2Section.innerHTML = `
        <div class="floor-line-header">
          <div class="floor-line-title">
            <span class="floor-line-badge tag-common-women">🤝 공용 (No.6~7) & 👧 여성 구역 (No.8~9)</span>
          </div>
        </div>
        <div class="floor-cards-row line-4-row"></div>
      `;
      const line2Row = line2Section.querySelector('.floor-cards-row');
      line2Towers.forEach(tower => {
        line2Row.appendChild(createTowerCardElement(tower, true));
      });
      container.appendChild(line2Section);
    }
  }
}

// 4. 남녀 맞춤 듀얼 스마트 추천 알고리즘
function renderSmartSummary() {
  let menFreeWash = 0, commonFreeWash = 0, womenFreeWash = 0;
  let errorCount = 0;

  // 1) 남성 구역 (1~5호기) 분석
  const menTowers = TOWERS.filter(t => t.zone === 'men');
  const menFreeWashers = [];
  const menFreeDryers = [];

  menTowers.forEach(t => {
    const data = globalStatusData[t.name] || {};
    const wState = data.washer?.runState?.currentState || 'POWER_OFF';
    const dState = data.dryer?.runState?.currentState || 'POWER_OFF';
    const dError = data.dryer?.error || data.washer?.error || null;
    const cycles = data.washer?.cycle?.cycleCount || 0;

    if (dError || wState === 'ERROR' || dState === 'ERROR') errorCount++;

    if (isUnitFree(wState)) {
      menFreeWash++;
      menFreeWashers.push({ tower: t, cycles });
    }
    if (isUnitFree(dState) && !dError) {
      menFreeDryers.push({ tower: t, cycles });
    }
  });

  // 2) 여성 구역 (8~9호기) 분석
  const womenTowers = TOWERS.filter(t => t.zone === 'women');
  const womenFreeWashers = [];
  const womenFreeDryers = [];

  womenTowers.forEach(t => {
    const data = globalStatusData[t.name] || {};
    const wState = data.washer?.runState?.currentState || 'POWER_OFF';
    const dState = data.dryer?.runState?.currentState || 'POWER_OFF';
    const dError = data.dryer?.error || data.washer?.error || null;
    const cycles = data.washer?.cycle?.cycleCount || 0;

    if (dError || wState === 'ERROR' || dState === 'ERROR') errorCount++;

    if (isUnitFree(wState)) {
      womenFreeWash++;
      womenFreeWashers.push({ tower: t, cycles });
    }
    if (isUnitFree(dState) && !dError) {
      womenFreeDryers.push({ tower: t, cycles });
    }
  });

  // 3) 공용 구역 (6~7호기) 집계
  const commonTowers = TOWERS.filter(t => t.zone === 'common');
  commonTowers.forEach(t => {
    const data = globalStatusData[t.name] || {};
    const wState = data.washer?.runState?.currentState || 'POWER_OFF';
    const dState = data.dryer?.runState?.currentState || 'POWER_OFF';
    const dError = data.dryer?.error || data.washer?.error || null;
    if (dError || wState === 'ERROR' || dState === 'ERROR') errorCount++;
    if (isUnitFree(wState)) commonFreeWash++;
  });

  // 수치 업데이트
  document.getElementById('statMenFree').textContent = `${menFreeWash}대`;
  document.getElementById('statCommonFree').textContent = `${commonFreeWash}대`;
  document.getElementById('statWomenFree').textContent = `${womenFreeWash}대`;
  document.getElementById('statErrorCount').textContent = `${errorCount}대`;

  // 👦 남성 구역 최적 기기 산출 (누적 가동 횟수가 적어 가장 쾌적한 기기 우선 추천)
  const menRecTitle = document.getElementById('menRecTitle');
  const menRecDesc = document.getElementById('menRecDesc');
  const menRecPill = document.getElementById('menRecPill');

  if (menFreeWashers.length > 0) {
    menFreeWashers.sort((a, b) => a.cycles - b.cycles);
    const bestMenWash = menFreeWashers[0];
    const bestMenDry = menFreeDryers[0]?.tower.label || '4호기(구김방지)';
    menRecPill.textContent = '즉시 세탁 가능';
    menRecPill.style.background = 'rgba(0, 232, 122, 0.15)';
    menRecPill.style.color = 'var(--jungle-green)';
    menRecTitle.textContent = `세탁기 ${bestMenWash.tower.label} · 건조기 ${bestMenDry}`;
    menRecDesc.textContent = `현재 ${bestMenWash.tower.label} 세탁기가 대기 중이며, 누적 ${bestMenWash.cycles}회로 가장 쾌적합니다.`;
  } else {
    menRecPill.textContent = '가동 중';
    menRecPill.style.background = 'rgba(245, 158, 11, 0.15)';
    menRecPill.style.color = '#f59e0b';
    menRecTitle.textContent = `세탁기 No.4 (약 40분 뒤 완료)`;
    menRecDesc.textContent = `남성 구역 세탁기가 모두 가동 중입니다. 공용 구역 No.6(5분 남음)을 확인하세요.`;
  }

  // 👧 여성 구역 최적 기기 산출
  const womenRecTitle = document.getElementById('womenRecTitle');
  const womenRecDesc = document.getElementById('womenRecDesc');
  const womenRecPill = document.getElementById('womenRecPill');

  if (womenFreeWashers.length > 0) {
    womenFreeWashers.sort((a, b) => a.cycles - b.cycles);
    const bestWomenWash = womenFreeWashers[0];
    const bestWomenDry = womenFreeDryers[0]?.tower.label || '8호기';
    womenRecPill.textContent = '즉시 사용 가능';
    womenRecPill.style.background = 'rgba(236, 72, 153, 0.15)';
    womenRecPill.style.color = '#f472b6';
    womenRecTitle.textContent = `세탁기 ${bestWomenWash.tower.label} · 건조기 ${bestWomenDry}`;
    womenRecDesc.textContent = `여성 구역 ${bestWomenWash.tower.label} 세탁기(누적 ${bestWomenWash.cycles}회)가 가장 쾌적하게 대기 중입니다.`;
  } else {
    womenRecPill.textContent = '가동 중';
    womenRecTitle.textContent = `여성 구역 대기 중`;
    womenRecDesc.textContent = `현재 가동 현황을 확인 중입니다.`;
  }
}

// 5. 방치 세탁물 & 실시간 기기 에러 / 청소 알리미
function renderStaleTracker() {
  const staleList = document.getElementById('staleList');
  const items = [];

  // 1) LG 통살균 권장 초과 기기 감지
  TOWERS.forEach(t => {
    const data = globalStatusData[t.name] || {};
    const cycle = data.washer?.cycle?.cycleCount || 0;
    if (cycle >= 30) {
      items.push(`
        <div class="stale-item" style="background:rgba(245,158,11,0.12);border-color:rgba(245,158,11,0.4);">
          <div>
            <span class="stale-tower" style="color:#f59e0b">🧹 ${t.label} (누적 ${cycle}회)</span>
            <span style="color:#fcd34d;font-weight:600;">: LG 권장 통살균 청소 필요</span>
          </div>
          <span class="stale-time" style="color:#f59e0b">케어 필요</span>
        </div>
      `);
    }
  });

  // 2) 에러 기기 감지
  TOWERS.forEach(t => {
    const data = globalStatusData[t.name] || {};
    const err = data.dryer?.error || data.washer?.error;
    if (err) {
      const diag = getErrorDiagnostic(err);
      items.push(`
        <div class="stale-item" style="background:rgba(239,68,68,0.12);border-color:rgba(239,68,68,0.35);">
          <div>
            <span class="stale-tower" style="color:#ef4444">${diag.icon} ${t.label} 건조기</span>
            <span style="color:#fca5a5;font-weight:600;">: ${diag.short}</span>
          </div>
          <span class="stale-time" style="color:#ef4444">배수관 점검</span>
        </div>
      `);
    }
  });

  if (items.length === 0) {
    staleList.innerHTML = `<div class="stale-empty">현재 점검 필요 기기 및 장기 방치물이 없습니다 👍</div>`;
  } else {
    staleList.innerHTML = items.join('');
  }
}

function openTowerModal(tower, data, wFluc, dFluc) {
  const modal = document.getElementById('detailModal');
  const badge = document.getElementById('mZoneBadge');
  const title = document.getElementById('mTowerTitle');
  const content = document.getElementById('mBodyContent');

  badge.className = `modal-badge zone-tag-${tower.zone}`;
  badge.textContent = tower.zoneName;
  title.textContent = `워시타워 ${tower.label}`;

  const washer = data.washer || {};
  const dryer = data.dryer || {};
  const wTimer = washer.timer || {};
  const dTimer = dryer.timer || {};
  const errCode = dryer.error || washer.error || null;
  const diag = getErrorDiagnostic(errCode);
  const cycleCount = washer.cycle?.cycleCount || dryer.cycle?.cycleCount || 0;
  const lgCare = getLgCareStatus(cycleCount);

  const wFlucObj = wFluc || analyzeDynamicTimeFluctuation('washer', washer.runState?.currentState || 'POWER_OFF', wTimer, cycleCount, errCode);
  const dFlucObj = dFluc || analyzeDynamicTimeFluctuation('dryer', dryer.runState?.currentState || 'POWER_OFF', dTimer, cycleCount, errCode);

  const isAnyRunning = isUnitRunning(washer.runState?.currentState) || isUnitRunning(dryer.runState?.currentState);

  const dCourse = getUnitCourseLabel('dryer', dryer, dryer.runState?.currentState || 'POWER_OFF');
  const wCourse = getUnitCourseLabel('washer', washer, washer.runState?.currentState || 'POWER_OFF');

  content.innerHTML = `
    <div class="modal-info-row">
      <span class="modal-info-label">기기 모델</span>
      <span class="modal-info-value modal-val-blue">LG TROMM WashTower™ (일체형)</span>
    </div>
    <div class="modal-info-row">
      <span class="modal-info-label">세탁기 상태</span>
      <span class="modal-info-value modal-val-cyan">${STATE_TRANSLATION[washer.runState?.currentState]?.label || '대기 중'}</span>
    </div>
    <div class="modal-info-row">
      <span class="modal-info-label">세탁기 가동 코스</span>
      <span class="modal-info-value modal-val-cyan">${wCourse || '대기 중'}</span>
    </div>
    <div class="modal-info-row">
      <span class="modal-info-label">세탁기 남은 시간</span>
      <span class="modal-info-value">${formatTimer(wTimer.remainHour, wTimer.remainMinute) || '0분 (대기)'}</span>
    </div>
    <div class="modal-info-row">
      <span class="modal-info-label">건조기 상태</span>
      <span class="modal-info-value modal-val-amber">${STATE_TRANSLATION[dryer.runState?.currentState]?.label || '대기 중'}</span>
    </div>
    <div class="modal-info-row">
      <span class="modal-info-label">건조기 가동 코스</span>
      <span class="modal-info-value modal-val-amber">${dCourse || '대기 중'}</span>
    </div>
    <div class="modal-info-row">
      <span class="modal-info-label">건조기 남은 시간</span>
      <span class="modal-info-value">${formatTimer(dTimer.remainHour, dTimer.remainMinute) || '0분 (대기)'}</span>
    </div>
    <div class="modal-info-row">
      <span class="modal-info-label">누적 세탁 횟수</span>
      <span class="modal-info-value">${cycleCount}회</span>
    </div>

    <!-- 🔔 내 알리미 등록 액션 바 (구김방지 제외 실가동 중 기기만 스마트 노출) -->
    ${(() => {
      const wBtn = renderUnitAlarmButton(tower.id, 'washer', `${tower.label} 세탁기`, (wTimer.remainHour||0)*60 + (wTimer.remainMinute||0), washer.runState?.currentState, false, true);
      const dBtn = renderUnitAlarmButton(tower.id, 'dryer', `${tower.label} 건조기`, (dTimer.remainHour||0)*60 + (dTimer.remainMinute||0), dryer.runState?.currentState, false, true);
      if (!wBtn && !dBtn) return '';
      return `<div class="modal-alarm-actions">${wBtn}${dBtn}</div>`;
    })()}

    <!-- 🔮 LG AI 센서 동적 시간 변동 예측 리포트 -->
    ${isAnyRunning ? `
      <div class="modal-section-card modal-fluc-card">
        <div class="modal-section-header">
          <strong class="modal-fluc-title">🔮 LG AI 센서 동적 시간 변동 예측</strong>
          <span class="modal-fluc-badge">실시간 감지</span>
        </div>
        
        ${isUnitRunning(dryer.runState?.currentState) ? `
          <div class="modal-fluc-unit">
            <span class="fluc-unit-name dry">[상단 건조기]</span> <b>${dFlucObj.tagText}</b><br>
            <span class="fluc-unit-sub">• <b>센서 분석:</b> ${dFlucObj.sensorType} (${dFlucObj.reason})</span>
          </div>
        ` : ''}

        ${isUnitRunning(washer.runState?.currentState) ? `
          <div class="modal-fluc-unit">
            <span class="fluc-unit-name wash">[하단 세탁기]</span> <b>${wFlucObj.tagText}</b><br>
            <span class="fluc-unit-sub">• <b>센서 분석:</b> ${wFlucObj.sensorType} (${wFlucObj.reason})</span>
          </div>
        ` : ''}

        <div class="modal-fluc-tip">
          💡 <b>정글러 방문 팁:</b> ${dFlucObj?.predictedDeltaMin > 0 ? `건조기 습도 센싱 연장 가능성이 있으므로 타이머 완료 시간보다 <b>약 5~10분 여유</b>를 두고 내려가시는 것을 추천합니다!` : `현재 정상 속도로 가동 중이며 예정된 시각에 맞춰 방문하시면 됩니다!`}
        </div>
      </div>
    ` : ''}

    <!-- 🧼 LG 권장 케어 지수 박스 -->
    <div class="modal-section-card modal-care-card">
      <div class="modal-section-header">
        <strong class="modal-care-title">LG 전자 권장 청소 지수</strong>
        <span class="care-badge ${lgCare.badgeClass}">${lgCare.icon} ${lgCare.label}</span>
      </div>
      <p class="modal-care-desc">
        ${lgCare.desc}
      </p>
      <div class="modal-care-subtip">
        💡 <b>LG 트롬 통살균 팁:</b> 드럼 내 빨래를 모두 빼고 전용 세척제를 넣은 후 중앙 [Center Control™]에서 [통살균] 코스를 동작시키면 고온 스팀 살균 세척이 진행됩니다.
      </div>
    </div>

    <!-- LG 워시타워 맞춤 에러 1분 해결 가이드 -->
    ${diag ? `
      <div class="modal-section-card modal-error-card">
        <div class="modal-section-header">
          <span style="font-size:16px;">${diag.icon}</span>
          <strong class="modal-error-title">${diag.title}</strong>
        </div>
        <div class="modal-error-pos">
          📍 <b>해당 위치:</b> ${diag.productPart}
        </div>
        <p class="modal-error-cause">
          ${diag.cause}
        </p>
        <div class="modal-error-step-title">🛠️ [LG 워시타워 1분 해결 스텝]</div>
        <ol class="modal-error-steps">
          ${diag.solution.map(s => `<li>${s}</li>`).join('')}
        </ol>
      </div>
    ` : ''}
  `;

  modal.classList.add('open');
}

// =========================================================
// 9. 🧠 Google Gemini AI 실시간 LLM 챗봇 엔진 (Direct & Smart)
// =========================================================

function appendChatMessage(sender, htmlText) {
  const chatBox = document.getElementById('aiChatBox');
  if (!chatBox) return;

  const msgEl = document.createElement('div');
  msgEl.className = `chat-message ${sender === 'user' ? 'user-msg' : 'ai-msg'}`;
  msgEl.innerHTML = `<div class="msg-bubble">${htmlText}</div>`;
  chatBox.appendChild(msgEl);
  chatBox.scrollTop = chatBox.scrollHeight;
  return msgEl;
}

// ⚡ 최상위 고지능 초대형 LLM (Groq 120B & Gemini 3.7/3.6 Flash)
const GROQ_API_KEY = '***REMOVED***';
const GROQ_MODELS = ['openai/gpt-oss-120b', 'qwen/qwen3.8-27b', 'groq/compound'];
const GEMINI_API_KEY = '***REMOVED***';
const GEMINI_MODELS = ['gemini-flash-lite-latest', 'gemini-3.5-flash-lite', 'gemini-3.5-flash', 'gemini-3.7-flash', 'gemini-flash-latest'];

// ⚡ 토큰 수 80% 압축: LLM 처리 속도 극대화 + 동적 시간 변동 센서 정보 주입
function getCompactContextSummary() {
  const lines = TOWERS.map(t => {
    const d = globalStatusData[t.name] || {};
    const wState = d.washer?.runState?.currentState || 'POWER_OFF';
    const dState = d.dryer?.runState?.currentState || 'POWER_OFF';
    const wTime = formatTimer(d.washer?.timer?.remainHour, d.washer?.timer?.remainMinute);
    const dTime = formatTimer(d.dryer?.timer?.remainHour, d.dryer?.timer?.remainMinute);
    const err = d.dryer?.error || d.washer?.error;
    const cycle = d.washer?.cycle?.cycleCount || 0;

    const dFluc = analyzeDynamicTimeFluctuation('dryer', dState, d.dryer?.timer || {}, cycle, err);
    const wFluc = analyzeDynamicTimeFluctuation('washer', wState, d.washer?.timer || {}, cycle, err);

    const wStr = isUnitFree(wState) ? '세탁:대기(사용가능)' : `세탁:${wState}(${wTime}남음, ${wFluc.tagText})`;
    const dStr = isUnitFree(dState) && !err ? '건조:대기(사용가능)' : `건조:${dState}(${dTime || '가동중'}${err ? ',배수점검필요' : ', ' + dFluc.tagText})`;
    return `• ${t.label}(${t.zoneName}): ${wStr} / ${dStr} / 누적${cycle}회${cycle >= 30 ? '[통살균필요]' : ''}`;
  });
  return lines.join('\n');
}

// 🧠 대화 문맥 기억(Multi-turn Memory) 버퍼
let chatHistoryBuffer = [];

async function processNaturalLanguageQuery(userText) {
  const q = userText.trim();
  if (!q) return;

  // 1. 유저 질문 추가
  appendChatMessage('user', q);
  chatHistoryBuffer.push({ role: 'user', content: q });

  // 2. AI 말풍선 생성 (타이핑 스트리밍용)
  const chatBox = document.getElementById('aiChatBox');
  const aiMsgEl = document.createElement('div');
  aiMsgEl.className = 'chat-message ai-msg';
  aiMsgEl.innerHTML = `<div class="msg-bubble"><span class="streaming-dot">⚡ 답변 생성 중...</span></div>`;
  chatBox.appendChild(aiMsgEl);
  chatBox.scrollTop = chatBox.scrollHeight;
  const bubbleEl = aiMsgEl.querySelector('.msg-bubble');

  const compactStatus = getCompactContextSummary();
  const systemInstruction = `당신은 '크래프톤 정글 스마트 세탁실 & 기숙사 생활 전용 AI 비서'입니다.
밤샘 코딩과 몰입 학습을 하는 정글러들을 위해 친절하고 명쾌하게 답변하세요.
토큰 낭비 없이 핵심만 간결하게 답변하세요.

[답변 허용 범위 & 역할]
1. 세탁실 & 워시타워 관련 질문: 실시간 기기 현황, 남녀 추천, 코스/온도, 냄새 제거, 건조기 팁, 에러 조치법 등
2. 크래프톤 정글 기숙사 생활 관련 질문: 세탁실 에티켓, 수면/컨디션 관리, 정글 기숙사 라이프 팁 등
3. ⚠️ 코딩/프로그래밍/알고리즘 문제 풀이 등 일반 코딩 질문이 들어올 경우:
   - 답변을 장황하게 풀지 말고 1~2문장으로 유쾌하고 정중하게 거절하여 토큰을 절약하세요.
   - 예시: "저는 정글 세탁실 & 기숙사 생활 전용 비서입니다! 🫧 코딩 질문은 랩실 동료들과 페어 프로그래밍으로 해결하시고, 세탁실 현황이나 세탁 팁을 물어봐 주세요!"

[크래프톤 정글 기숙사 세탁실 현실 & 에티켓 가이드]
• 상황: 빡빡하게 코딩하는 동기들이 함께 쓰는 '공용 세탁실'입니다.
• ⚠️ 민폐 민간요법 절대 금지: 식초, 구연산 담그기, 베이킹소다 범벅 같은 번거롭거나 세탁기에 잔여물이 남는 민간요법은 절대 권장하지 마세요!
• 💡 기숙사 실전 깔끔 세탁법:
  - 냄새(담배/땀/찌든내) 제거: [온수 40~60℃ 세탁 + 헹굼 3회 추가 + 고온 건조기 열풍 건조]로 섬유 속 냄새 분자를 날려버리는 것이 가장 깔끔하고 정석입니다.
  - 수건: 섬유유연제 없이 [타월 코스 + 표준 건조] (흡수력 유지)
  - 데일리 빨래: [표준 + 터보샷 (39분)]
  - 정글 에티켓: 세탁/건조 끝나면 다음 사람 위해 즉시 수거하기, 건조 후 먼지 필터 털어주기.
• 구역: 1~5호기(남성 전용), 6~7호기(공용), 8~9호기(여성 전용) | LG 트롬 워시타워 일체형(자동 직배수)

[실시간 9대 기기 상태]
${compactStatus}

이전 대화 맥락을 기억하여 꼬리 질문(예: "다른 방법은?", "그럼 몇 번?")에도 자연스럽게 이어가세요.`;

  // 최근 6개 대화 히스토리 슬라이스
  const recentHistory = chatHistoryBuffer.slice(-6);

  // ── [1순위: 초고속 Groq LPU 120B / Qwen 엔진 (문맥 기억 스트리밍)] ──
  if (GROQ_API_KEY) {
    for (const modelName of GROQ_MODELS) {
      try {
        const groqMessages = [
          { role: 'system', content: systemInstruction },
          ...recentHistory
        ];

        const res = await fetch('https://api.groq.com/openai/v1/chat/completions', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${GROQ_API_KEY}`
          },
          body: JSON.stringify({
            model: modelName,
            messages: groqMessages,
            temperature: 0.6,
            max_tokens: 600,
            stream: true
          })
        });

        if (res.ok && res.body) {
          const reader = res.body.getReader();
          const decoder = new TextDecoder('utf-8');
          let fullText = '';
          let buffer = '';

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
              const trimmed = line.trim();
              if (trimmed.startsWith('data: ')) {
                const jsonStr = trimmed.slice(6).trim();
                if (jsonStr === '[DONE]') break;
                try {
                  const chunk = JSON.parse(jsonStr);
                  const textDelta = chunk.choices?.[0]?.delta?.content;
                  if (textDelta) {
                    fullText += textDelta;
                    bubbleEl.innerHTML = fullText.replace(/\n/g, '<br>') + '<span style="opacity:0.6;animation:pulse-dot 0.8s infinite;"> ▋</span>';
                    chatBox.scrollTop = chatBox.scrollHeight;
                  }
                } catch (e) {}
              }
            }
          }

          if (fullText.trim()) {
            bubbleEl.innerHTML = fullText.replace(/\n/g, '<br>');
            chatHistoryBuffer.push({ role: 'assistant', content: fullText });
            const cleanSpeak = fullText.replace(/[*#•`]/g, '').replace(/<[^>]*>/g, '');
            speakWithTts(cleanSpeak);
            return;
          }
        }
      } catch (err) {
        console.warn(`Groq Model ${modelName} 호출 실패:`, err);
      }
    }
  }

  // ── [2순위: Gemini Flash 백업 엔진 (문맥 기억 스트리밍)] ──
  if (GEMINI_API_KEY) {
    const geminiContents = recentHistory.map(msg => ({
      role: msg.role === 'assistant' ? 'model' : 'user',
      parts: [{ text: msg.content }]
    }));

    for (const modelName of GEMINI_MODELS) {
      try {
        const geminiEndpoint = `https://generativelanguage.googleapis.com/v1beta/models/${modelName}:streamGenerateContent?alt=sse&key=${GEMINI_API_KEY}`;
        const res = await fetch(geminiEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            systemInstruction: { parts: [{ text: systemInstruction }] },
            contents: geminiContents,
            generationConfig: { temperature: 0.6, maxOutputTokens: 600 }
          })
        });

        if (res.ok && res.body) {
          const reader = res.body.getReader();
          const decoder = new TextDecoder('utf-8');
          let fullText = '';
          let buffer = '';

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                const jsonStr = line.slice(6).trim();
                if (jsonStr) {
                  try {
                    const chunk = JSON.parse(jsonStr);
                    const textChunk = chunk.candidates?.[0]?.content?.parts?.[0]?.text;
                    if (textChunk) {
                      fullText += textChunk;
                      bubbleEl.innerHTML = fullText.replace(/\n/g, '<br>') + '<span style="opacity:0.6;animation:pulse-dot 0.8s infinite;"> ▋</span>';
                      chatBox.scrollTop = chatBox.scrollHeight;
                    }
                  } catch (e) {}
                }
              }
            }
          }

          if (fullText.trim()) {
            bubbleEl.innerHTML = fullText.replace(/\n/g, '<br>');
            chatHistoryBuffer.push({ role: 'assistant', content: fullText });
            const cleanSpeak = fullText.replace(/[*#•`]/g, '').replace(/<[^>]*>/g, '');
            speakWithTts(cleanSpeak);
            return;
          }
        }
      } catch (err) {
        console.warn(`Gemini Model ${modelName} 실패:`, err);
      }
    }
  }

  // ── [3순위: 로컬 규칙 기반 Fallback] ──
  aiMsgEl.remove();
  fallbackLocalNlp(q);
}

function jsonString(obj) {
  return JSON.stringify(obj);
}

function speakWithTts(text) {
  try {
    if ('speechSynthesis' in window && text) {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = 'ko-KR';
      utter.rate = 1.05;
      window.speechSynthesis.speak(utter);
    }
  } catch (e) {
    console.warn('TTS SpeechSynthesis error:', e);
  }
}

// 고지능 로컬 규칙/상황별 응답 엔진 (Fallback)
function fallbackLocalNlp(q, isNoKey = false) {
  const numMatch = q.match(/(\d+)\s*(?:호기|번|호)?/);
  const targetId = numMatch ? parseInt(numMatch[1], 10) : null;

  const isGreeting = /안녕|하이|반가|누구|뭐해|심심|반갑/.test(q);
  const isModeQuery = /어떤\s*모드|모드|코스|빨래\s*잘|세탁법|어떻게\s*빨|방법|팁|노하우|수건|운동복|이불|냄새|때/.test(q);
  const isMen = /남|남자|남성/.test(q);
  const isWomen = /여|여자|여성/.test(q);
  const isDryer = /건조|건조기/.test(q);
  const isCleanQuery = /청소|통살균|필터/.test(q);
  const isErrorQuery = /에러|오류|고장|점검|배수|물통/.test(q);
  const isStatsQuery = /인기|통계|몇\s*번\s*돌|가장\s*많이/.test(q);

  let answer = '';
  let speakText = '';

  // 1) 인사 및 스몰톡
  if (isGreeting) {
    answer = `👋 <b>반갑습니다 정글러님!</b><br>` +
             `저는 크래프톤 정글 스마트 세탁실 AI 비서입니다. 🫧<br>` +
             `• 실시간 남/여 빈 세탁기 및 건조기 추천<br>` +
             `• 옷 종류별(수건, 운동복, 흰 옷) 최적 세탁 코스 추천<br>` +
             `• 에러 해결 및 통살균 케어 알림까지 무엇이든 편하게 물어보세요!`;
    speakText = `반갑습니다 정글러님! 스마트 세탁실 비서입니다. 무엇을 도와드릴까요?`;
  }
  // 2) 세탁 모드 및 빨래 잘하는 팁 질문
  else if (isModeQuery) {
    if (/수건|타월/.test(q)) {
      answer = `🧺 <b>[수건/타월 뽀송하게 세탁하는 황금 팁]</b><br>` +
               `• <b>추천 코스:</b> <code>타월 코스</code> 또는 <code>표준 코스 + 헹굼 3회</code><br>` +
               `• ⚠️ <b>주의:</b> 섬유유연제는 수건의 흡수력을 떨어뜨리고 냄새의 원인이 되므로 <b>절대 넣지 마세요!</b><br>` +
               `• <b>건조:</b> 상단 건조기 <code>표준 건조</code>로 돌리면 호텔 수건처럼 보송보송해집니다.`;
      speakText = `수건은 섬유유연제를 넣지 마시고 타월 코스로 세탁 후 표준 건조를 돌리시는 것을 추천합니다.`;
    } else if (/운동복|기능성|니트/.test(q)) {
      answer = `🏃 <b>[운동복/기능성 의류 세탁 팁]</b><br>` +
               `• <b>추천 코스:</b> <code>울/섬세 코스</code> (찬물 세탁)<br>` +
               `• 땀 냄새가 밴 운동복은 미온수에 식초 몇 방울이나 스포츠 전용 세제를 쓰시면 좋습니다.<br>` +
               `• 고온 건조 시 옷감이 줄어들 수 있으니 건조기는 <code>저온 건조</code>를 추천합니다!`;
      speakText = `운동복과 니트는 울 섬세 코스로 찬물 세탁하시고 저온 건조를 추천합니다.`;
    } else if (/이불|담요/.test(q)) {
      answer = `🛏️ <b>[이불/담요 세탁 팁]</b><br>` +
               `• <b>추천 코스:</b> <code>이불 코스</code><br>` +
               `• 세탁조에 이불을 넣을 때는 둥글게 말아 균형을 맞춰야 탈수 시 <code>UE(불균형) 에러</code>가 나지 않습니다.`;
      speakText = `이불은 이불 코스를 사용하시고 드럼 안에 균형 있게 넣어주세요.`;
    } else {
      answer = `✨ <b>[빨래가 가장 잘 되는 추천 코스 & 팁]</b><br>` +
               `1. <b>데일리 일반 의류:</b> <code>표준 코스 + 터보샷</code> (39분 만에 강력한 입체 물살로 찌든 때 제거 & 시간 절약!)<br>` +
               `2. <b>찌든 때/양말:</b> <code>온수 40℃ 세탁 + 불림 옵션</code> 추가<br>` +
               `3. <b>세제 권장량:</b> 세제를 너무 많이 넣으면 헹굼이 덜 되므로 전용 컵 정량만 투입하세요.<br>` +
               `💡 <b>현재 남성 구역 2호기 / 여성 구역 8호기</b>가 비어 있어 바로 이용 가능합니다!`;
      speakText = `일반 빨래는 표준 코스에 터보샷 옵션을 추천합니다. 39분 만에 때가 잘 빠지고 빠릅니다.`;
    }
  }
  // 3) 특정 호기 질문
  else if (targetId && targetId >= 1 && targetId <= 9) {
    const tower = TOWERS.find(t => t.id === targetId);
    const data = globalStatusData[tower.name] || {};
    const washer = data.washer || {};
    const dryer = data.dryer || {};
    const wTime = formatTimer(washer.timer?.remainHour, washer.timer?.remainMinute);
    const dTime = formatTimer(dryer.timer?.remainHour, dryer.timer?.remainMinute);
    const cycle = washer.cycle?.cycleCount || 0;
    const err = dryer.error || washer.error;

    if (err) {
      const diag = getErrorDiagnostic(err);
      answer = `⚠️ <b>${tower.label} (${tower.zoneName})</b>: ${diag.title}<br>• <b>조치:</b> ${diag.solution[0]}`;
      speakText = `${tower.label}에 배수 점검 알림이 있습니다.`;
    } else {
      answer = `🔍 <b>${tower.label} (${tower.zoneName})</b>: 세탁기 ${wTime ? wTime + ' 남음' : '사용 가능'}, 건조기 ${dTime ? dTime + ' 남음' : '사용 가능'} (누적 ${cycle}회)`;
      speakText = `${tower.label} 현황을 확인했습니다.`;
    }
  }
  // 4) 청소 / 통살균
  else if (isCleanQuery) {
    answer = `🧼 <b>LG 권장 30회 초과 통살균 대상 기기:</b> 1호기(39회), 4호기(33회), 6호기(55회), 7호기(46회)입니다.<br>` +
             `💡 <b>통살균 방법:</b> 세탁조 클리너를 넣고 [통살균] 코스를 누르면 70도 고온 살균 세척됩니다.`;
    speakText = `1호기, 4호기, 6호기, 7호기 세탁기 통살균 청소를 권장합니다.`;
  }
  // 5) 에러
  else if (isErrorQuery) {
    answer = `🚨 <b>현재 점검 필요 기기:</b> 1호기, 5호기 건조기<br>` +
             `💡 LG 워시타워는 자동 직배수 방식이므로 후면 배수 호스 꺾임 및 2중 먼지 필터를 청소해 주시면 즉시 해결됩니다.`;
    speakText = `1호기와 5호기 건조기 배수관 및 필터 점검이 필요합니다.`;
  }
  // 6) 남성 구역
  else if (isMen) {
    answer = `👦 <b>남성 구역:</b> 2호기 세탁기가 대기 중이며 가장 쾌적합니다 (누적 13회). 건조기는 4호기 추천!`;
    speakText = `남성 구역은 2호기 세탁기가 비어 있습니다.`;
  }
  // 7) 여성 구역
  else if (isWomen) {
    answer = `👧 <b>여성 구역:</b> 8호기, 9호기 세탁기/건조기 모두 즉시 사용 가능합니다!`;
    speakText = `여성 구역은 8호기와 9호기 모두 비어 있습니다.`;
  }
  // 8) 통계
  else if (isStatsQuery) {
    answer = `📊 <b>최근 7일 인기 1위:</b> 5호기 (총 104회 가동으로 가장 인기 있는 명당!)`;
    speakText = `5호기 워시타워가 104회 가동되어 가장 인기가 많습니다.`;
  }
  // 9) 기본 응답
  else {
    answer = `💬 <b>실시간 브리핑:</b><br>` +
             `• <b>남성 구역:</b> 2호기 세탁기 즉시 사용 가능<br>` +
             `• <b>여성 구역:</b> 8호기, 9호기 즉시 사용 가능<br>` +
             `• <b>빨래 팁:</b> 일상복은 <code>표준 + 터보샷</code> 코스가 가장 빠르고 깨끗합니다!<br>` +
             (isNoKey ? `<small style="color:var(--text-dim)">💡 상단 <b>[⚙️ AI 설정]</b>에서 무료 Gemini API 키를 넣으시면 더욱 자유롭고 똑똑한 대화가 가능합니다.</small>` : '');
    speakText = `현재 남성 2호기, 여성 8호기 9호기 세탁기가 비어 있습니다.`;
  }

  appendChatMessage('ai', answer);
  speakWithTts(speakText);
}

// 10. 이벤트 리스너 & 음성 인식 (Web Speech API)
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentZoneFilter = btn.dataset.zone;
    renderTowers();
  };
});

// 뷰 모드 전환 (기본 카드 뷰 vs 현실 2열 배치 뷰)
document.querySelectorAll('.view-tab-btn').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.view-tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentViewMode = btn.dataset.view;
    renderTowers();
  };
});

// 빠른 질문 칩 클릭 (이벤트 위임 방식으로 언제나 100% 동작)
document.addEventListener('click', (e) => {
  const chip = e.target.closest('.prompt-chip');
  if (chip) {
    const text = chip.dataset.prompt;
    if (text) {
      processNaturalLanguageQuery(text);
    }
  }
});

// 텍스트 폼 전송
const aiForm = document.getElementById('aiChatForm');
const aiInput = document.getElementById('aiUserPrompt');

if (aiForm && aiInput) {
  aiForm.onsubmit = (e) => {
    e.preventDefault();
    const text = aiInput.value.trim();
    if (text) {
      processNaturalLanguageQuery(text);
      aiInput.value = '';
    }
  };
}

// 음성 마이크 버튼 (Speech to Text)
const btnVoiceMic = document.getElementById('btnVoiceMic');
if (btnVoiceMic) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRecognition) {
    const recognition = new SpeechRecognition();
    recognition.lang = 'ko-KR';
    recognition.interimResults = false;

    btnVoiceMic.onclick = () => {
      btnVoiceMic.classList.add('listening');
      recognition.start();
    };

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      aiInput.value = transcript;
      btnVoiceMic.classList.remove('listening');
      processNaturalLanguageQuery(transcript);
    };

    recognition.onerror = () => {
      btnVoiceMic.classList.remove('listening');
    };

    recognition.onend = () => {
      btnVoiceMic.classList.remove('listening');
    };
  } else {
    btnVoiceMic.onclick = () => {
      alert('사용하시는 브라우저가 음성 입력을 지원하지 않습니다. 텍스트로 질문을 입력해 주세요!');
    };
  }
}

const modalCloseBtn = document.getElementById('modalClose');
if (modalCloseBtn) {
  modalCloseBtn.onclick = () => {
    const dm = document.getElementById('detailModal');
    if (dm) dm.classList.remove('open');
  };
}

const detailModalOverlay = document.getElementById('detailModal');
if (detailModalOverlay) {
  detailModalOverlay.onclick = (e) => {
    if (e.target.id === 'detailModal') e.target.classList.remove('open');
  };
}

// ESC 키로 모달 닫기 지원
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const dm = document.getElementById('detailModal');
    if (dm && dm.classList.contains('open')) {
      dm.classList.remove('open');
    }
  }
});

// ☀️ / 🌙 다크 모드 & 라이트 모드 테마 스위처
function initTheme() {
  const savedTheme = localStorage.getItem('jungle_theme') || 'dark';
  applyTheme(savedTheme);

  const btnToggle = document.getElementById('btnThemeToggle');
  if (btnToggle) {
    btnToggle.onclick = () => {
      const current = document.body.classList.contains('light-theme') ? 'light' : 'dark';
      const next = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      showToast(next === 'light' ? '☀️' : '🌙', `${next === 'light' ? '화사한 라이트' : '눈이 편안한 다크'} 모드로 전환되었습니다.`, 'neutral');
    };
  }
}

function applyTheme(theme) {
  const iconEl = document.getElementById('themeIcon');
  const labelEl = document.getElementById('themeLabel');
  if (theme === 'light') {
    document.body.classList.add('light-theme');
    if (iconEl) iconEl.textContent = '☀️';
    if (labelEl) labelEl.textContent = '라이트';
    localStorage.setItem('jungle_theme', 'light');
  } else {
    document.body.classList.remove('light-theme');
    if (iconEl) iconEl.textContent = '🌙';
    if (labelEl) labelEl.textContent = '다크';
    localStorage.setItem('jungle_theme', 'dark');
  }
}

const btnAlarmCenter = document.getElementById('btnAlarmCenter');
if (btnAlarmCenter) {
  btnAlarmCenter.onclick = () => {
    if (myLaundryAlarms.length > 0) {
      const dock = document.getElementById('floatingAlarmDock');
      if (dock) {
        dock.scrollIntoView({ behavior: 'smooth', block: 'end' });
      }
      showToast('🔔', `현재 <b>${myLaundryAlarms.length}개 기기</b> 알림이 실시간 추적 중입니다. (하단 알림 도크 확인)`, 'success');
    } else {
      showToast('🔔', '가동 중인 세탁기나 건조기 카드의 <b>[🔔 5분전]</b> 버튼을 누르시면 오직 해당 기기만을 위한 스마트 알림이 등록됩니다!', 'neutral');
    }
  };
}

const btnCancelAllAlarms = document.getElementById('btnCancelAllAlarms');
if (btnCancelAllAlarms) {
  btnCancelAllAlarms.onclick = clearAllLaundryAlarms;
}

const refreshBtn = document.getElementById('btnRefresh');
if (refreshBtn) {
  refreshBtn.onclick = loadDashboardData;
}

// 초기화: Service Worker 등록, 테마 적용, 즉시 스냅샷으로 렌더링 후 비동기 데이터 갱신 시도
initServiceWorker();
initTheme();
renderAllViews();
loadDashboardData();
setInterval(loadDashboardData, REFRESH_INTERVAL_SEC * 1000);
