// x_tweetdetail.mjs — X (Twitter) TweetDetail GraphQL istemcisi (ortak cekirdek).
//
// Bird cookie extraction (Chrome "Profile 2") + TweetDetail GraphQL cagrisi.
// Hem fetch_articles.mjs (article body) hem fetch_thread.mjs (thread) bunu kullanir.
// withArticlePlainText=true -> article body de gelir (thread icin zararsiz).
//
// Kullanim (modul): import { createClient } from './x_tweetdetail.mjs'
//   const client = await createClient();  // cookie extraction
//   const r = await client.fetchTweetDetail(id);  // {ok, data} | {ok:false,status,error}
//
// Kullanim (CLI): node x_tweetdetail.mjs <tweet_id>   -> ham TweetDetail JSON stdout'a
//
// KIRILGAN: QID (TweetDetail query hash) Twitter'la degisebilir. Kirildiginda
// x-graphql-recovery skill'i / enc0der-bird query-ids ile guncelle. Bkz HANDOFF 8.2.

const BIRD_ROOT = '/Users/ahmet/Projects/x-analyst-tracker/jawond-bird';
const QID = 'nBS-WpgA6ZG0CyNHD517JQ';
const BASE = 'https://x.com/i/api/graphql';
const AUTH = 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA';

const TWEET_FEATURES = {
  rweb_video_screen_enabled: false, rweb_cashtags_enabled: true,
  profile_label_improvements_pcf_label_in_post_enabled: true,
  responsive_web_profile_redirect_enabled: true,
  rweb_tipjar_consumption_enabled: true, verified_phone_label_enabled: false,
  creator_subscriptions_tweet_preview_api_enabled: true,
  responsive_web_graphql_timeline_navigation_enabled: true,
  responsive_web_graphql_skip_user_profile_image_extensions_enabled: false,
  premium_content_api_read_enabled: false,
  communities_web_enable_tweet_community_results_fetch: true,
  c9s_tweet_anatomy_moderator_badge_enabled: true,
  responsive_web_grok_analyze_button_fetch_trends_enabled: false,
  responsive_web_grok_analyze_post_followups_enabled: false,
  rweb_cashtags_composer_attachment_enabled: true,
  responsive_web_jetfuel_frame: true,
  responsive_web_grok_share_attachment_enabled: true,
  responsive_web_grok_annotations_enabled: true,
  articles_preview_enabled: true,
  responsive_web_edit_tweet_api_enabled: true,
  rweb_conversational_replies_downvote_enabled: false,
  graphql_is_translatable_rweb_tweet_is_translatable_enabled: true,
  view_counts_everywhere_api_enabled: true,
  longform_notetweets_consumption_enabled: true,
  responsive_web_twitter_article_tweet_consumption_enabled: true,
  content_disclosure_indicator_enabled: false,
  content_disclosure_ai_generated_indicator_enabled: false,
  responsive_web_grok_show_grok_translated_post: false,
  responsive_web_grok_analysis_button_from_backend: true,
  post_ctas_fetch_enabled: false,
  freedom_of_speech_not_reach_fetch_enabled: true,
  standardized_nudges_misinfo: true,
  tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled: true,
  longform_notetweets_rich_text_read_enabled: true,
  longform_notetweets_inline_media_enabled: true,
  responsive_web_grok_image_annotation_enabled: true,
  responsive_web_grok_imagine_annotation_enabled: true,
  responsive_web_grok_community_note_auto_translation_is_enabled: false,
  responsive_web_enhance_cards_enabled: false,
};

const TWEET_FIELD_TOGGLES = {
  withPayments: false, withAuxiliaryUserLabels: true,
  withArticleRichContentState: true,
  withArticlePlainText: true,
  withArticleSummaryText: true,
  withArticleVoiceOver: false, withGrokAnalyze: false,
  withDisallowedReplyControls: false,
};

export async function extractCookies(profile = 'Profile 2') {
  const { extractCookiesFromChrome } = await import(`${BIRD_ROOT}/dist/lib/cookies.js`);
  const cookieRes = await extractCookiesFromChrome(profile);
  if (!cookieRes.cookies.authToken || !cookieRes.cookies.ct0) {
    throw new Error('Cookie extraction failed: ' + cookieRes.error);
  }
  return cookieRes.cookies; // { authToken, ct0 }
}

function buildHeaders({ authToken, ct0 }) {
  return {
    authorization: AUTH, 'content-type': 'application/json',
    'x-csrf-token': ct0, 'x-twitter-auth-type': 'OAuth2Session',
    'x-twitter-active-user': 'yes', 'x-twitter-client-language': 'en',
    cookie: `auth_token=${authToken}; ct0=${ct0}`,
    'user-agent': 'Mozilla/5.0 (Macintosh) Chrome/120.0',
    origin: 'https://x.com', referer: 'https://x.com/',
  };
}

// Cookie extraction'i bir kez yapip { fetchTweetDetail } donduren istemci.
export async function createClient(profile = 'Profile 2') {
  const cookies = await extractCookies(profile);
  const headers = buildHeaders(cookies);

  async function fetchTweetDetail(tweetId) {
    const variables = {
      focalTweetId: tweetId, with_rux_injections: false,
      rankingMode: 'Relevance', includePromotedContent: true,
      withCommunity: true, withQuickPromoteEligibilityTweetFields: true,
      withBirdwatchNotes: true, withVoice: true,
    };
    const params = new URLSearchParams({
      variables: JSON.stringify(variables),
      features: JSON.stringify(TWEET_FEATURES),
      fieldToggles: JSON.stringify(TWEET_FIELD_TOGGLES),
    });
    const url = `${BASE}/${QID}/TweetDetail?${params}`;
    const r = await fetch(url, { headers });
    if (!r.ok) return { ok: false, status: r.status, error: (await r.text()).slice(0, 200) };
    return { ok: true, data: await r.json() };
  }

  return { cookies, fetchTweetDetail };
}

// CLI: node x_tweetdetail.mjs <tweet_id>  -> ham JSON stdout
if (import.meta.url === `file://${process.argv[1]}`) {
  const id = process.argv[2];
  if (!id) { console.error('Usage: node x_tweetdetail.mjs <tweet_id>'); process.exit(1); }
  const client = await createClient();
  console.error('cookies OK');
  const r = await client.fetchTweetDetail(id);
  if (!r.ok) { console.error(JSON.stringify(r)); process.exit(2); }
  console.log(JSON.stringify(r.data));
}
