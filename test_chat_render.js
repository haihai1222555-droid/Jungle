// 채팅 답변을 화면에 그릴 때 링크가 제대로 되는지 확인한다.
//
//     node test_chat_render.js
//
// AI 가 쓴 글은 전부 escape 해서 그린다. 그런데 주소만은 <a> 로 만들어 준다
// (안 그러면 사람이 복사해서 주소창에 붙여야 한다). 그 예외가 구멍이 되면 안 된다.
// javascript: 주소가 링크가 되면 누르는 순간 실행되므로, 그런 것이 막히는지 본다.
//
// 브라우저 없이 app.js 에서 그 함수들만 떼어내 돌린다. 따로 설치할 것은 없다.
const fs = require('fs');
const vm = require('vm');

const APP = require('path').join(__dirname, 'app.js');
const src = fs.readFileSync(APP, 'utf8');

// 필요한 함수만 떼어내 돌린다 (브라우저 없이)
function grab(name) {
  const re = new RegExp('(?:^|\\n)(?:const |let |function )' + name + '[\\s\\S]*?(?=\\n(?:const |let |function |// =)|$)');
  const m = src.match(re);
  if (!m) throw new Error(name + ' 을 app.js 에서 못 찾음');
  return m[0];
}

const ctx = { console };
vm.createContext(ctx);
for (const n of ['escapeHtml', 'fmtChatChunk', 'safeChatUrl', 'CHAT_LINK_RE', 'renderChatText']) {
  vm.runInContext(grab(n), ctx);
}
const render = (t) => vm.runInContext('renderChatText(' + JSON.stringify(t) + ')', ctx);

let fail = 0;
function check(name, got, want) {
  const ok = typeof want === 'function' ? want(got) : got === want;
  if (!ok) { fail++; console.log(`  [X ] ${name}\n       받음: ${got}\n       기대: ${want}`); }
  else console.log(`  [OK] ${name}  ->  ${got}`);
}

console.log('== 링크가 되어야 하는 것 ==');
check('그냥 적힌 주소',
  render('자세히: https://krafton-jungle.duckdns.org/doc'),
  '자세히: <a class="chat-link" href="https://krafton-jungle.duckdns.org/doc" target="_blank" rel="noopener noreferrer">https://krafton-jungle.duckdns.org/doc</a>');
check('마크다운 링크',
  render('[정글 대시보드](https://krafton-jungle.duckdns.org/)'),
  '<a class="chat-link" href="https://krafton-jungle.duckdns.org/" target="_blank" rel="noopener noreferrer">정글 대시보드</a>');
check('문장 끝 마침표는 링크 밖으로',
  render('여기 보세요 https://example.com/a.'),
  s => s.includes('href="https://example.com/a"') && s.endsWith('</a>.'));
check('괄호 안 주소',
  render('(https://example.com)'),
  s => s.includes('href="https://example.com"') && s.startsWith('(') && s.endsWith(')'));
check('주소 두 개',
  render('https://a.com 과 https://b.com'),
  s => (s.match(/<a /g) || []).length === 2);
check('http 도 된다', render('http://a.com'), s => s.includes('href="http://a.com"'));

console.log('\n== 링크가 되면 안 되는 것 ==');
check('javascript: 주소', render('javascript:alert(1)'), s => !s.includes('<a '));
check('마크다운에 javascript:', render('[눌러](javascript:alert(1))'),
  s => !s.includes('<a ') && !s.includes('javascript:alert(1)"'));
check('data: 주소', render('data:text/html,<script>alert(1)</script>'),
  s => !s.includes('<a ') && !s.includes('<script>'));
check('따옴표 섞인 주소는 링크 안 만듦',
  render('[x](https://a.com" onmouseover="alert(1))'),
  s => !s.includes('onmouseover="alert'));
check('태그는 그대로 글자', render('<img src=x onerror=alert(1)>'),
  s => !s.includes('<img') && s.includes('&lt;img'));
check('주소처럼 생긴 글자 뒤 태그',
  render('https://a.com<script>alert(1)</script>'),
  s => !s.includes('<script>'));

console.log('\n== 원래 있던 서식은 그대로 ==');
check('굵게', render('**중요** 합니다'), '<b>중요</b> 합니다');
check('줄바꿈', render('한 줄\n두 줄'), '한 줄<br>두 줄');
check('링크와 굵게 함께',
  render('**여기** https://a.com 보세요'),
  s => s.startsWith('<b>여기</b> ') && s.includes('<a '));
check('빈 입력', render(''), '');
check('null', render(null), '');

console.log(fail ? `\n${fail}개 틀렸습니다.` : '\n모두 통과했습니다.');
process.exit(fail ? 1 : 0);
