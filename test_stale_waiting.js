// 화면의 '방치' 목록 판정만 떼어 와서 돌린다.
//
// 이름에 '방치' 가 있는 위젯이 방치를 찾지 않았다. 이제 서버가 적은 시각으로 센다.
// 서버 기록을 못 받았을 때 '방치물이 없다' 고 말하면 안 되는 것도 함께 본다.
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

eval(grab('getLgCareStatus') + grab('staleWaitingList') + grab('staleDryerCareList'));

let bad = 0;
function check(what, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { bad++; console.log('  틀림: %s — %j 가 나왔는데 %j 여야 한다', what, got, want); }
  else console.log('  %s → %j', what, got);
}

const now = 1_800_000_000;
const min = m => now - m * 60;

check('15분 안 된 것은 아직 방치가 아니다',
  staleWaitingList({ '3호기': { dryer: min(14) } }, now, 15), []);
check('15분이 되면 방치',
  staleWaitingList({ '3호기': { dryer: min(15) } }, now, 15),
  [{ label: '3호기', name: '건조기', mins: 15 }]);
check('세탁기와 건조기를 따로 센다',
  staleWaitingList({ '2호기': { washer: min(40), dryer: min(20) } }, now, 15)
    .map(x => x.name + x.mins), ['세탁기40', '건조기20']);
check('오래된 것이 위로',
  staleWaitingList({ '1호기': { dryer: min(20) }, '6호기': { dryer: min(90) } }, now, 15)
    .map(x => x.label), ['6호기', '1호기']);
check('기준 분은 서버가 정한다',
  staleWaitingList({ '1호기': { dryer: min(20) } }, now, 30), []);
check('기록이 비어 있으면 아무것도 안 만든다', staleWaitingList({}, now, 15), []);
check('서버 기록이 없으면(undefined) 터지지 않는다', staleWaitingList(undefined, now, 15), []);
check('숫자가 아닌 값은 무시', staleWaitingList({ '1호기': { dryer: 'x' } }, now, 15), []);

// ── 건조기 통살균 ─────────────────────────────────────────────────
// 건조기가 전부 74~85회인데 위젯에는 세탁기 하나뿐이었다. 건조기는 안 봤다.
const T = [1, 2, 3, 4].map(i => ({ id: i, label: i + '호기' }));
check('30회 이상만 올린다',
  staleDryerCareList({ '1호기': { count: 78 }, '2호기': { count: 12 }, '3호기': { count: 30 }, '4호기': { count: 29 } }, T)
    .map(x => x.label + x.count), ['1호기78', '3호기30']);
check('횟수 많은 것이 위로',
  staleDryerCareList({ '1호기': { count: 40 }, '2호기': { count: 85 } }, T).map(x => x.label), ['2호기', '1호기']);
check('기록을 못 받았으면(빈 값) 아무것도 안 올린다', staleDryerCareList({}, T), []);
check('undefined 여도 터지지 않는다', staleDryerCareList(undefined, T), []);
check('횟수가 숫자가 아니면 무시', staleDryerCareList({ '1호기': { count: '78' } }, T), []);
check('0회는 올리지 않는다', staleDryerCareList({ '1호기': { count: 0 } }, T), []);

console.log(bad ? bad + '곳 틀렸다' : '모두 통과했습니다.');
process.exit(bad ? 1 : 0);
