// 건조기 줄이 세탁기 줄과 같은 모양으로 나오는지, 그리고 열쇠가 맞는지 본다.
// 열쇠는 실제로 들어오는 이름표('5호기')로 확인한다. 'No.5' 로만 확인해서
// "1호기호기" 버그를 놓친 적이 있다.
const fs = require('fs');
const path = require('path');
// 이 파일이 있는 곳의 app.js 를 본다. 자리를 옮겨도 돌아가야 한다.
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
eval(grab('getLgCareStatus') + grab('fmtCareDay') + grab('careKeyOf')
   + grab('careWasherCleanedText') + grab('renderDryerCareRow'));

let bad = 0;
function show(desc, label, data) {
  careData = { dryer: data, washer: {} };
  const html = renderDryerCareRow(label);
  const text = html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  const pct = (html.match(/width: (\d+)%/) || [])[1];
  console.log(desc.padEnd(18), '|', text, '| 막대', pct + '%');
}

// 서버가 실제로 쓰는 이름표
const five = { '5호기': { count: 4, cleanedAt: null } };
['5호기', 'No.5', '워시타워_5'].forEach(l => show('이름표 ' + l, l, five));
if (renderDryerCareRow('5호기').indexOf('(4회)') < 0) { console.log('!! 열쇠가 안 맞는다'); bad++; }

show('0회', '5호기', { '5호기': { count: 0, cleanedAt: null } });
show('통살균 뒤', '5호기', { '5호기': { count: 0, cleanedAt: 1759190000 } });
show('22회', '5호기', { '5호기': { count: 22, cleanedAt: 1759190000 } });
show('31회', '5호기', { '5호기': { count: 31, cleanedAt: 1759190000 } });
show('값 없음', '5호기', {});

careData = { dryer: {}, washer: { '5호기': { cleanedAt: 1759190000 } } };
console.log('세탁기 마지막   |', JSON.stringify(careWasherCleanedText('5호기')));
if (!careWasherCleanedText('5호기')) { console.log('!! 세탁기 열쇠가 안 맞는다'); bad++; }

console.log(bad ? bad + '곳 틀렸다' : '모두 통과했습니다.');
process.exit(bad ? 1 : 0);
