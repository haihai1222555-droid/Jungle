// 화면 쪽 사이클 판정만 떼어 와서 돌린다.
//
// 이 판정이 틀리면 내 알림이 남의 빨래에 들러붙는다. 실제로 그랬다 —
// 건조기는 사이클 번호가 없다고 보고 시간으로만 짐작했는데, 기기가
// 돌고 있으면 예상 완료 시각을 그 남은 시간으로 계속 밀어서 짐작이
// 영영 성립하지 않았다.
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');

function grab(name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) throw new Error(name + ' 없음');
  let depth = 0, started = false;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') { depth++; started = true; }
    else if (src[j] === '}') { depth--; if (started && depth === 0) return src.slice(i, j + 1); }
  }
  throw new Error(name + ' 끝을 못 찾음');
}

let careData = { dryer: {}, washer: {} };
eval(grab('careDryerCount') + grab('alarmCycleDelta'));

let bad = 0;
function check(what, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { bad++; console.log('  틀림: %s — %j 가 나왔는데 %j 여야 한다', what, got, want); }
  else console.log('  %s → %j', what, got);
}

// ── 건조기: 우리가 센 횟수를 사이클 번호로 쓴다 ─────────────────────
careData = { dryer: { '3호기': { count: 4 } }, washer: {} };
const dry = { unitType: 'dryer', towerId: 3, dryerCountAtRegister: 4 };
check('아직 내 사이클', alarmCycleDelta(dry, {}), 0);

careData.dryer['3호기'].count = 5;
check('내 빨래가 끝났다', alarmCycleDelta(dry, {}), 1);

careData.dryer['3호기'].count = 7;
check('그 뒤로 더 돌았다', alarmCycleDelta(dry, {}), 3);

// 통살균을 돌리면 셈이 0 으로 되돌아간다. 내 사이클은 한참 전에 끝났다.
careData.dryer['3호기'].count = 0;
check('통살균으로 되돌아가도 지난 사이클', alarmCycleDelta(dry, {}), 2);

// ── 세탁기: 기기가 주는 누적 횟수 ───────────────────────────────────
const wash = { unitType: 'washer', towerId: 3, cycleAtRegister: 11 };
const tower = c => ({ washer: { cycle: { cycleCount: c } } });
check('세탁기 내 사이클', alarmCycleDelta(wash, tower(11)), 0);
check('세탁기 한 번 지남', alarmCycleDelta(wash, tower(12)), 1);
check('세탁기 통살균 되돌림', alarmCycleDelta(wash, tower(2)), 2);

// ── 모르는 경우는 모른다고 해야 한다 ────────────────────────────────
check('예전 알림(번호 없음)', alarmCycleDelta({ unitType: 'dryer', towerId: 3 }, {}), null);
check('값이 아직 안 온 기기', alarmCycleDelta(wash, {}), null);
careData = { dryer: {}, washer: {} };
check('케어 기록이 아직 없음', alarmCycleDelta(dry, {}), null);

console.log(bad ? bad + '곳 틀렸다' : '모두 통과했습니다.');
process.exit(bad ? 1 : 0);
