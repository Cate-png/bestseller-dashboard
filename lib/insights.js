// "트렌드 키워드" / "주목할 흐름" 계산 함수들.
// 외부 AI API는 쓰지 않고, 화면이 이미 들고 있는 데이터(storeData/categoryData)를
// 그대로 받아서 빈도/규칙 기반으로 계산합니다. Supabase에 새로 쿼리하지 않습니다.
//
// 입력값 storeData는 { "교보문고": [row, ...], "예스24": [...], "알라딘": [...] }
// 형태로, app/page.js가 이미 조회해서 Dashboard에 내려주는 것과 동일한 모양입니다
// (종합 탭이면 storeData 전체, 분야 탭이면 categoryData[분야] 전체를 그대로 넘기면 됨).

// 키워드로 세지 않을 단어들: 서점명/출판사 프로모션 문구/저자 역할 표기 등
// "의미 없는 단어"에 해당하는 것들을 규칙으로 정리한 목록입니다.
const STOPWORDS = new Set(
  [
    "교보문고", "예스24", "yes24", "알라딘", "위즈덤하우스",
    "리커버", "한정판", "특별판", "개정판", "증보판", "애장판",
    "완역본", "완역", "무삭제", "합본", "세트", "기념판", "기념",
    "에디션", "버전", "특전판", "더블특전판", "더블", "오리지널",
    "초판", "신판", "단독", "돌파", "출간", "신간", "베스트",
    "베스트셀러", "추천", "선정", "전권", "만부", "수록", "전집",
    "시리즈", "한국어판", "증정", "사은품", "포함", "동봉", "패키지",
    "스페셜", "프리미엄", "콜렉션", "박스", "특가",
    "저", "역", "지음", "옮김", "그림", "편저", "편역", "감수",
    "지은이", "옮긴이", "글", "저자", "그림작가", "엮음", "엮은이",
  ].map((w) => w.toLowerCase())
);

// 조사로 추정되는 꼬리표(긴 것부터 매칭). 완벽한 형태소 분석은 아니지만,
// 규칙 기반으로 "습관의"->"습관", "미래를"->"미래" 정도는 하나로 묶어줍니다.
const PARTICLE_SUFFIXES = [
  "으로부터", "에게서", "이라는", "라는", "에서의", "와의", "과의",
  "에서", "으로", "까지", "부터", "에게", "한테",
  "은", "는", "이", "가", "을", "를", "의", "에", "도", "만", "과", "와", "랑", "로",
];

function stripParticle(token) {
  for (const suf of PARTICLE_SUFFIXES) {
    if (token.length - suf.length >= 2 && token.endsWith(suf)) {
      return token.slice(0, token.length - suf.length);
    }
  }
  return token;
}

function tokenize(text) {
  if (!text) return [];
  // 괄호/대괄호 안 내용(주로 판형·특전·기념 문구)은 통째로 제거
  const cleaned = text.replace(/[[(（【][^)\]）】]*[)\]）】]/g, " ");
  return cleaned
    .split(/[\s,·:;\-–—\/&×~'"!?.]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

// storeData( { 서점명: [row,...] } )를 isbn13 기준으로 중복 제거한 도서
// 목록으로 바꿉니다. 같은 책이 여러 서점 TOP에 동시에 올라 있어도 한 권으로
// 세고, 등장한 서점 목록을 bookstores에 모아둡니다.
export function buildUniqueBooks(storeData, bookstores) {
  const byKey = new Map();
  for (const bookstore of bookstores) {
    for (const row of storeData[bookstore] || []) {
      const key = row.isbn13 || `${bookstore}::${row.title}`;
      const existing = byKey.get(key);
      if (existing) {
        existing.bookstores.push(bookstore);
      } else {
        byKey.set(key, { ...row, bookstores: [bookstore] });
      }
    }
  }
  return [...byKey.values()];
}

// 도서 제목/저자에서 의미 있는 키워드를 뽑아 "몇 권에서 등장했는지"로 순위를 매깁니다.
export function extractTrendKeywords(books, topN = 10) {
  const bookCountByKeyword = new Map();

  for (const book of books) {
    const rawTokens = [...tokenize(book.title), ...tokenize(book.author)];

    const keywordsInThisBook = new Set();
    for (const raw of rawTokens) {
      if (/^[0-9]/.test(raw)) continue; // 숫자로 시작(연도/수량/판수 등)하면 제외
      const stripped = stripParticle(raw);
      if (stripped.length < 2) continue;
      if (STOPWORDS.has(stripped.toLowerCase())) continue;
      keywordsInThisBook.add(stripped);
    }

    for (const kw of keywordsInThisBook) {
      bookCountByKeyword.set(kw, (bookCountByKeyword.get(kw) || 0) + 1);
    }
  }

  return [...bookCountByKeyword.entries()]
    .filter(([, count]) => count >= 2) // 최소 2권 이상 겹쳐야 "키워드"로 인정
    .sort((a, b) => b[1] - a[1])
    .slice(0, topN)
    .map(([keyword, bookCount]) => ({ keyword, bookCount }));
}

// 여러 도서에 공통적으로 나타나는 주제/현상을 규칙 기반으로 몇 가지 후보로
// 뽑아본 뒤, 근거가 되는 도서 수가 많은 순으로 상위 몇 개만 반환합니다.
// (AI 호출 없이 순수 집계 규칙만 사용)
export function extractNotableFlows(books, max = 3) {
  const candidates = [];

  // 1) 여러 서점에 동시에 오른 도서
  const multiStoreBooks = books.filter((b) => (b.bookstores?.length || 1) >= 2);
  if (multiStoreBooks.length > 0) {
    candidates.push({
      description: `${multiStoreBooks.length}권이 2개 이상의 서점에서 동시에 순위에 올라 있어요.`,
      bookCount: multiStoreBooks.length,
    });
  }

  // 2) 신규 진입 도서 비중
  const newEntries = books.filter(
    (b) => b.rank_change === null && b.match_status === "matched"
  );
  if (newEntries.length > 0) {
    candidates.push({
      description: `신규 진입 도서가 ${newEntries.length}권 눈에 띕니다.`,
      bookCount: newEntries.length,
    });
  }

  // 3) 같은 저자의 책이 동시에 여러 권 순위권에 있는 경우
  const byAuthor = new Map();
  for (const b of books) {
    const authors = (b.author || "")
      .split(/[,/]/)
      .map((a) => a.trim())
      .filter((a) => a.length >= 2);
    for (const a of authors) {
      if (!byAuthor.has(a)) byAuthor.set(a, []);
      byAuthor.get(a).push(b);
    }
  }
  const repeatAuthors = [...byAuthor.entries()]
    .filter(([, arr]) => arr.length >= 2)
    .sort((a, b) => b[1].length - a[1].length);
  if (repeatAuthors.length > 0) {
    const [author, arr] = repeatAuthors[0];
    candidates.push({
      description: `'${author}' 저자의 도서가 ${arr.length}권 동시에 순위권에 있어요.`,
      bookCount: arr.length,
    });
  }

  // 4) 한 출판사의 책이 여러 권 몰려 있는 경우
  const byPublisher = new Map();
  for (const b of books) {
    const p = (b.publisher || "").trim();
    if (!p) continue;
    if (!byPublisher.has(p)) byPublisher.set(p, []);
    byPublisher.get(p).push(b);
  }
  const publisherEntries = [...byPublisher.entries()].sort(
    (a, b) => b[1].length - a[1].length
  );
  if (publisherEntries.length > 0 && publisherEntries[0][1].length >= 3) {
    const [publisher, arr] = publisherEntries[0];
    candidates.push({
      description: `'${publisher}'에서 낸 책이 ${arr.length}권 순위에 올라 있습니다.`,
      bookCount: arr.length,
    });
  }

  // 5) 상위 키워드 기반 흐름 (트렌드 키워드 계산을 그대로 재사용)
  const topKeywords = extractTrendKeywords(books, 3);
  for (const { keyword, bookCount } of topKeywords) {
    candidates.push({
      description: `'${keyword}' 관련 표현이 담긴 도서가 ${bookCount}권 있어요.`,
      bookCount,
    });
  }

  return candidates.sort((a, b) => b.bookCount - a.bookCount).slice(0, max);
}
