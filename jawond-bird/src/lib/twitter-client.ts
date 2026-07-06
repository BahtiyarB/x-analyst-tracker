/**
 * Twitter GraphQL API client for posting tweets and replies
 */

import type { TwitterCookies } from './cookies.js';
import queryIds from './query-ids.json' with { type: 'json' };

const TWITTER_API_BASE = 'https://x.com/i/api/graphql';

// Query IDs rotate frequently; the values in query-ids.json are refreshed by
// scripts/update-query-ids.ts. The fallback values keep the client usable if
// the file is missing or incomplete.
const FALLBACK_QUERY_IDS = {
  CreateTweet: 'TAJw1rBsjAtdNgTdlo2oeg',
  CreateRetweet: 'ojPdsZsimiJrUGLR1sjUtA',
  FavoriteTweet: 'lI07N6Otwv1PhnEgXILM7A',
  TweetDetail: 'nBS-WpgA6ZG0CyNHD517JQ',
  SearchTimeline: 'Tp1sewRU1AsZpBWhqCZicQ',
  UserTweets: 'hr4gzZONlq23okjU8fIe_A',
  UserByScreenName: '2qvSHpkWTMS9i0zJAwDNiA',
} as const;

type OperationName = keyof typeof FALLBACK_QUERY_IDS;

const QUERY_IDS: Record<OperationName, string> = {
  ...FALLBACK_QUERY_IDS,
  ...(queryIds as Partial<Record<OperationName, string>>),
};

// X's GraphQL endpoints validate a mandatory feature-flag set that changes over
// time; a stale/incomplete set returns HTTP 422 GRAPHQL_VALIDATION_FAILED.
// Updated 2026-07-06 for the current TweetDetail/SearchTimeline schema (adds the
// grok/*, payments, premium_content, jetfuel, profile_label, rweb_video_screen
// flags X began requiring in 2026). If reads/searches start 422-ing again,
// diff this against a live x.com request's `features=` param in DevTools.
const TWEET_FEATURES = {
  rweb_video_screen_enabled: false,
  rweb_cashtags_enabled: true,
  profile_label_improvements_pcf_label_in_post_enabled: true,
  responsive_web_profile_redirect_enabled: true,
  rweb_tipjar_consumption_enabled: true,
  verified_phone_label_enabled: false,
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
} as const;

// fieldToggles X now requires alongside featureSwitches for tweet-listing ops.
const TWEET_FIELD_TOGGLES = {
  withPayments: false,
  withAuxiliaryUserLabels: true,
  withArticleRichContentState: true,
  withArticlePlainText: false,
  withArticleSummaryText: false,
  withArticleVoiceOver: false,
  withGrokAnalyze: false,
  withDisallowedReplyControls: false,
} as const;

// featureSwitches for UserByScreenName, per the current x.com client bundle.
const USER_BY_SCREEN_NAME_FEATURES = {
  hidden_profile_subscriptions_enabled: true,
  profile_label_improvements_pcf_label_in_post_enabled: true,
  responsive_web_profile_redirect_enabled: true,
  rweb_tipjar_consumption_enabled: true,
  verified_phone_label_enabled: false,
  subscriptions_verification_info_is_identity_verified_enabled: true,
  subscriptions_verification_info_verified_since_enabled: true,
  highlights_tweets_tab_ui_enabled: true,
  responsive_web_twitter_article_notes_tab_enabled: true,
  subscriptions_feature_can_gift_premium: true,
  creator_subscriptions_tweet_preview_api_enabled: true,
  responsive_web_graphql_skip_user_profile_image_extensions_enabled: false,
  responsive_web_graphql_timeline_navigation_enabled: true,
} as const;

const USER_BY_SCREEN_NAME_FIELD_TOGGLES = {
  withAuxiliaryUserLabels: true,
  withPayments: false,
} as const;

type GraphqlUserResult = {
  rest_id?: string;
  // X moved screen_name/name from `legacy` to `core` in its 2026 schema revision;
  // keep both so older/newer payload shapes are both tolerated.
  core?: {
    screen_name?: string;
    name?: string;
  };
  legacy?: {
    screen_name?: string;
    name?: string;
  };
};

type GraphqlTweetResult = {
  rest_id?: string;
  legacy?: {
    full_text?: string;
    created_at?: string;
    reply_count?: number;
    retweet_count?: number;
    favorite_count?: number;
    conversation_id_str?: string;
    in_reply_to_status_id_str?: string | null;
  };
  core?: {
    user_results?: {
      result?: GraphqlUserResult;
    };
  };
};

export interface TweetResult {
  success: boolean;
  tweetId?: string;
  error?: string;
}

export interface TweetData {
  id: string;
  text: string;
  author: {
    username: string;
    name: string;
  };
  createdAt?: string;
  replyCount?: number;
  retweetCount?: number;
  likeCount?: number;
  conversationId?: string;
  inReplyToStatusId?: string;
}

export interface GetTweetResult {
  success: boolean;
  tweet?: TweetData;
  error?: string;
}

export interface SearchResult {
  success: boolean;
  tweets?: TweetData[];
  error?: string;
}

export interface PaginatedTweetsResult {
  success: boolean;
  tweets?: TweetData[];
  nextCursor?: string;
  error?: string;
}

export interface UserData {
  id: string;
  username: string;
  name: string;
}

export interface GetUserResult {
  success: boolean;
  user?: UserData;
  error?: string;
}

export interface CurrentUserResult {
  success: boolean;
  user?: {
    id: string;
    username: string;
    name: string;
  };
  error?: string;
}

export interface TwitterClientOptions {
  cookies: TwitterCookies;
  userAgent?: string;
}

interface CreateTweetResponse {
  data?: {
    create_tweet?: {
      tweet_results?: {
        result?: {
          rest_id?: string;
          legacy?: {
            full_text?: string;
          };
        };
      };
    };
  };
  errors?: Array<{ message: string; code?: number }>;
}

export class TwitterClient {
  private authToken: string;
  private ct0: string;
  private userAgent: string;

  constructor(options: TwitterClientOptions) {
    if (!options.cookies.authToken || !options.cookies.ct0) {
      throw new Error('Both authToken and ct0 cookies are required');
    }
    this.authToken = options.cookies.authToken;
    this.ct0 = options.cookies.ct0;
    this.userAgent =
      options.userAgent ||
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
  }

  private findTweetInInstructions(
    instructions:
      | Array<{
          entries?: Array<{
            content?: {
              itemContent?: {
                tweet_results?: {
                  result?: {
                    rest_id?: string;
                    legacy?: {
                      full_text?: string;
                      created_at?: string;
                      reply_count?: number;
                      retweet_count?: number;
                      favorite_count?: number;
                    };
                    core?: {
                      user_results?: {
                        result?: {
                          legacy?: {
                            screen_name?: string;
                            name?: string;
                          };
                        };
                      };
                    };
                  };
                };
              };
            };
          }>;
        }>
      | undefined,
    tweetId: string,
  ) {
    if (!instructions) return undefined;

    for (const instruction of instructions) {
      for (const entry of instruction.entries || []) {
        const result = entry.content?.itemContent?.tweet_results?.result;
        if (result?.rest_id === tweetId) {
          return result;
        }
      }
    }

    return undefined;
  }

  private getHeaders(): Record<string, string> {
    return {
      authorization:
        'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
      'content-type': 'application/json',
      'x-csrf-token': this.ct0,
      'x-twitter-auth-type': 'OAuth2Session',
      'x-twitter-active-user': 'yes',
      'x-twitter-client-language': 'en',
      cookie: `auth_token=${this.authToken}; ct0=${this.ct0}`,
      'user-agent': this.userAgent,
      origin: 'https://x.com',
      referer: 'https://x.com/',
    };
  }

  private mapTweetResult(result: GraphqlTweetResult | undefined): TweetData | undefined {
    const user = result?.core?.user_results?.result;
    // Screen name/name live under `core` in the current schema, but fall back to
    // `legacy` in case an older payload shape is ever encountered.
    const username = user?.core?.screen_name || user?.legacy?.screen_name;
    const name = user?.core?.name || user?.legacy?.name || username;
    if (!result?.legacy || !username) return undefined;
    return {
      id: result.rest_id || '',
      text: result.legacy.full_text || '',
      createdAt: result.legacy.created_at,
      replyCount: result.legacy.reply_count,
      retweetCount: result.legacy.retweet_count,
      likeCount: result.legacy.favorite_count,
      conversationId: result.legacy.conversation_id_str,
      inReplyToStatusId: result.legacy.in_reply_to_status_id_str ?? undefined,
      author: {
        username,
        name: name || username,
      },
    };
  }

  private parseTweetsFromInstructions(
    instructions:
      | Array<{
          entries?: Array<{
            content?: {
              itemContent?: {
                tweet_results?: {
                  result?: GraphqlTweetResult;
                };
              };
            };
          }>;
        }>
      | undefined,
  ): TweetData[] {
    const tweets: TweetData[] = [];
    for (const instruction of instructions ?? []) {
      for (const entry of instruction.entries ?? []) {
        const result = entry.content?.itemContent?.tweet_results?.result;
        const mapped = this.mapTweetResult(result);
        if (mapped) tweets.push(mapped);
      }
    }
    return tweets;
  }

  private async fetchTweetDetail(tweetId: string): Promise<
    | {
        success: true;
        data: {
          tweetResult?: { result?: GraphqlTweetResult };
          threaded_conversation_with_injections_v2?: {
            instructions?: Array<{
              entries?: Array<{
                content?: {
                  itemContent?: {
                    tweet_results?: {
                      result?: GraphqlTweetResult;
                    };
                  };
                };
              }>;
            }>;
          };
        };
      }
    | { success: false; error: string }
  > {
    const variables = {
      focalTweetId: tweetId,
      with_rux_injections: false,
      rankingMode: 'Relevance',
      includePromotedContent: true,
      withCommunity: true,
      withQuickPromoteEligibilityTweetFields: true,
      withBirdwatchNotes: true,
      withVoice: true,
    };

    const features = TWEET_FEATURES;

    const params = new URLSearchParams({
      variables: JSON.stringify(variables),
      features: JSON.stringify(features),
      fieldToggles: JSON.stringify(TWEET_FIELD_TOGGLES),
    });

    const url = `${TWITTER_API_BASE}/${QUERY_IDS.TweetDetail}/TweetDetail?${params}`;

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: this.getHeaders(),
      });

      if (!response.ok) {
        const text = await response.text();
        return { success: false, error: `HTTP ${response.status}: ${text.slice(0, 200)}` };
      }

      const data = (await response.json()) as {
        data?: {
          tweetResult?: { result?: GraphqlTweetResult };
          threaded_conversation_with_injections_v2?: {
            instructions?: Array<{
              entries?: Array<{
                content?: {
                  itemContent?: {
                    tweet_results?: {
                      result?: GraphqlTweetResult;
                    };
                  };
                };
              }>;
            }>;
          };
        };
        errors?: Array<{ message: string; code?: number }>;
      };

      if (data.errors && data.errors.length > 0) {
        return { success: false, error: data.errors.map((e) => e.message).join(', ') };
      }

      return { success: true, data: data.data ?? {} };
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) };
    }
  }

  /**
   * Get tweet details by ID
   */
  async getTweet(tweetId: string): Promise<GetTweetResult> {
    const response = await this.fetchTweetDetail(tweetId);
    if (!response.success) {
      return response;
    }

    const tweetResult =
      (response.data.tweetResult as { result?: GraphqlTweetResult } | undefined)?.result ??
      this.findTweetInInstructions(
        response.data.threaded_conversation_with_injections_v2?.instructions as
          | Array<{
              entries?: Array<{
                content?: {
                  itemContent?: {
                    tweet_results?: {
                      result?: GraphqlTweetResult;
                    };
                  };
                };
              }>;
            }>
          | undefined,
        tweetId,
      );

    const mapped = this.mapTweetResult(tweetResult);
    if (mapped) {
      return { success: true, tweet: mapped };
    }
    return { success: false, error: 'Tweet not found in response' };
  }

  /**
   * Resolve a handle (screen name) to its user id/name via UserByScreenName.
   */
  async getUserByScreenName(handle: string): Promise<GetUserResult> {
    const screenName = handle.replace(/^@/, '');
    const variables = { screen_name: screenName };

    const params = new URLSearchParams({
      variables: JSON.stringify(variables),
      features: JSON.stringify(USER_BY_SCREEN_NAME_FEATURES),
      fieldToggles: JSON.stringify(USER_BY_SCREEN_NAME_FIELD_TOGGLES),
    });

    const url = `${TWITTER_API_BASE}/${QUERY_IDS.UserByScreenName}/UserByScreenName?${params}`;

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: this.getHeaders(),
      });

      if (!response.ok) {
        const text = await response.text();
        return { success: false, error: `HTTP ${response.status}: ${text.slice(0, 200)}` };
      }

      const data = (await response.json()) as {
        data?: {
          user?: {
            result?: GraphqlUserResult;
          };
        };
        errors?: Array<{ message: string }>;
      };

      if (data.errors && data.errors.length > 0) {
        return { success: false, error: data.errors.map((e) => e.message).join(', ') };
      }

      const result = data.data?.user?.result;
      const username = result?.core?.screen_name || result?.legacy?.screen_name;
      const name = result?.core?.name || result?.legacy?.name || username;

      if (!result?.rest_id || !username) {
        return { success: false, error: 'User not found in response' };
      }

      return {
        success: true,
        user: {
          id: result.rest_id,
          username,
          name: name || username,
        },
      };
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) };
    }
  }

  /**
   * Fetch a user's recent tweets (their profile timeline) via UserTweets.
   *
   * Pass `cursor` (the `value` of a "Bottom" TimelineTimelineCursor entry from
   * a previous call's `nextCursor`) to page further back into the user's
   * history. Returns the tweets found on this page plus the next page's
   * bottom cursor (if any) so callers can keep paginating until the cursor
   * stops advancing or no new tweets are returned.
   */
  async getUserTweets(userId: string, count = 20, cursor?: string): Promise<PaginatedTweetsResult> {
    const variables: Record<string, unknown> = {
      userId,
      count,
      includePromotedContent: false,
      withQuickPromoteEligibilityTweetFields: false,
      withVoice: true,
    };
    if (cursor) variables.cursor = cursor;

    const params = new URLSearchParams({
      variables: JSON.stringify(variables),
      features: JSON.stringify(TWEET_FEATURES),
      fieldToggles: JSON.stringify(TWEET_FIELD_TOGGLES),
    });

    const url = `${TWITTER_API_BASE}/${QUERY_IDS.UserTweets}/UserTweets?${params}`;

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: this.getHeaders(),
      });

      if (!response.ok) {
        const text = await response.text();
        return { success: false, error: `HTTP ${response.status}: ${text.slice(0, 200)}` };
      }

      const data = (await response.json()) as {
        data?: {
          user?: {
            result?: {
              timeline?: {
                timeline?: {
                  instructions?: Array<{
                    type?: string;
                    entries?: Array<{
                      content?: {
                        entryType?: string;
                        cursorType?: string;
                        value?: string;
                        itemContent?: {
                          tweet_results?: {
                            result?: GraphqlTweetResult;
                          };
                        };
                      };
                    }>;
                  }>;
                };
              };
            };
          };
        };
        errors?: Array<{ message: string }>;
      };

      if (data.errors && data.errors.length > 0) {
        return { success: false, error: data.errors.map((e) => e.message).join(', ') };
      }

      const instructions = data.data?.user?.result?.timeline?.timeline?.instructions ?? [];
      const tweets: TweetData[] = [];
      let nextCursor: string | undefined;

      for (const instruction of instructions) {
        // TimelinePinEntry carries a pinned tweet in a singular `entry`, which
        // we skip so it doesn't distort chronological ordering; the regular
        // TimelineAddEntries `entries` list already covers recent tweets.
        if (instruction.type === 'TimelinePinEntry') continue;
        for (const entry of instruction.entries ?? []) {
          const content = entry.content;
          // TimelineTimelineCursor entries mark pagination points, not tweets.
          // The "Bottom" cursor is what we need to request the next page.
          if (content?.entryType === 'TimelineTimelineCursor') {
            if (content.cursorType === 'Bottom' && content.value) {
              nextCursor = content.value;
            }
            continue;
          }
          const result = content?.itemContent?.tweet_results?.result;
          const mapped = this.mapTweetResult(result);
          if (mapped) tweets.push(mapped);
        }
      }

      return { success: true, tweets: cursor ? tweets : tweets.slice(0, count), nextCursor };
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) };
    }
  }

  /**
   * Post a new tweet
   */
  async tweet(text: string): Promise<TweetResult> {
    const variables = {
      tweet_text: text,
      dark_request: false,
      media: {
        media_entities: [],
        possibly_sensitive: false,
      },
      semantic_annotation_ids: [],
    };

    const features = {
      premium_content_api_read_enabled: false,
      communities_web_enable_tweet_community_results_fetch: true,
      c9s_tweet_anatomy_moderator_badge_enabled: true,
      responsive_web_grok_analyze_button_fetch_trends_enabled: false,
      responsive_web_grok_analyze_post_followups_enabled: false,
      responsive_web_jetfuel_frame: true,
      responsive_web_grok_share_attachment_enabled: true,
      responsive_web_edit_tweet_api_enabled: true,
      graphql_is_translatable_rweb_tweet_is_translatable_enabled: true,
      view_counts_everywhere_api_enabled: true,
      longform_notetweets_consumption_enabled: true,
      responsive_web_twitter_article_tweet_consumption_enabled: true,
      tweet_awards_web_tipping_enabled: false,
      responsive_web_grok_show_grok_translated_post: false,
      responsive_web_grok_analysis_button_from_backend: true,
      creator_subscriptions_quote_tweet_preview_enabled: false,
      longform_notetweets_rich_text_read_enabled: true,
      longform_notetweets_inline_media_enabled: true,
      profile_label_improvements_pcf_label_in_post_enabled: true,
      responsive_web_profile_redirect_enabled: false,
      rweb_tipjar_consumption_enabled: true,
      verified_phone_label_enabled: false,
      articles_preview_enabled: true,
      responsive_web_grok_community_note_auto_translation_is_enabled: false,
      responsive_web_graphql_skip_user_profile_image_extensions_enabled: false,
      freedom_of_speech_not_reach_fetch_enabled: true,
      standardized_nudges_misinfo: true,
      tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled: true,
      responsive_web_grok_image_annotation_enabled: true,
      responsive_web_grok_imagine_annotation_enabled: true,
      responsive_web_graphql_timeline_navigation_enabled: true,
      responsive_web_enhance_cards_enabled: false,
    };

    return this.createTweet(variables, features);
  }

  /**
   * Reply to an existing tweet
   */
  async reply(text: string, replyToTweetId: string): Promise<TweetResult> {
    const variables = {
      tweet_text: text,
      reply: {
        in_reply_to_tweet_id: replyToTweetId,
        exclude_reply_user_ids: [],
      },
      dark_request: false,
      media: {
        media_entities: [],
        possibly_sensitive: false,
      },
      semantic_annotation_ids: [],
    };

    const features = {
      premium_content_api_read_enabled: false,
      communities_web_enable_tweet_community_results_fetch: true,
      c9s_tweet_anatomy_moderator_badge_enabled: true,
      responsive_web_grok_analyze_button_fetch_trends_enabled: false,
      responsive_web_grok_analyze_post_followups_enabled: false,
      responsive_web_jetfuel_frame: true,
      responsive_web_grok_share_attachment_enabled: true,
      responsive_web_edit_tweet_api_enabled: true,
      graphql_is_translatable_rweb_tweet_is_translatable_enabled: true,
      view_counts_everywhere_api_enabled: true,
      longform_notetweets_consumption_enabled: true,
      responsive_web_twitter_article_tweet_consumption_enabled: true,
      tweet_awards_web_tipping_enabled: false,
      responsive_web_grok_show_grok_translated_post: false,
      responsive_web_grok_analysis_button_from_backend: true,
      creator_subscriptions_quote_tweet_preview_enabled: false,
      longform_notetweets_rich_text_read_enabled: true,
      longform_notetweets_inline_media_enabled: true,
      profile_label_improvements_pcf_label_in_post_enabled: true,
      responsive_web_profile_redirect_enabled: false,
      rweb_tipjar_consumption_enabled: true,
      verified_phone_label_enabled: false,
      articles_preview_enabled: true,
      responsive_web_grok_community_note_auto_translation_is_enabled: false,
      responsive_web_graphql_skip_user_profile_image_extensions_enabled: false,
      freedom_of_speech_not_reach_fetch_enabled: true,
      standardized_nudges_misinfo: true,
      tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled: true,
      responsive_web_grok_image_annotation_enabled: true,
      responsive_web_grok_imagine_annotation_enabled: true,
      responsive_web_graphql_timeline_navigation_enabled: true,
      responsive_web_enhance_cards_enabled: false,
    };

    return this.createTweet(variables, features);
  }

  private async createTweet(
    variables: Record<string, unknown>,
    features: Record<string, boolean>,
  ): Promise<TweetResult> {
    const url = `${TWITTER_API_BASE}/${QUERY_IDS.CreateTweet}/CreateTweet`;

    const body = JSON.stringify({
      variables,
      features,
      queryId: QUERY_IDS.CreateTweet,
    });

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: this.getHeaders(),
        body,
      });

      if (!response.ok) {
        const text = await response.text();
        return {
          success: false,
          error: `HTTP ${response.status}: ${text.slice(0, 200)}`,
        };
      }

      const data = (await response.json()) as CreateTweetResponse;

      if (data.errors && data.errors.length > 0) {
        return {
          success: false,
          error: data.errors.map((e) => e.message).join(', '),
        };
      }

      const tweetId = data.data?.create_tweet?.tweet_results?.result?.rest_id;
      if (tweetId) {
        return {
          success: true,
          tweetId,
        };
      }

      return {
        success: false,
        error: 'Tweet created but no ID returned',
      };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  /**
   * Search for tweets matching a query
   */
  async search(query: string, count = 20): Promise<SearchResult> {
    const variables = {
      rawQuery: query,
      count,
      querySource: 'typed_query',
      product: 'Latest',
    };

    const features = TWEET_FEATURES;

    // SearchTimeline is registered as a GraphQL "query" but X's backend only
    // accepts it as a POST with a JSON body (GET with querystring params 404s,
    // even though the same param shape works for TweetDetail/UserTweets/etc.
    // as GET). Confirmed live 2026-07-06: GET -> 404 empty body, POST -> 200.
    const url = `${TWITTER_API_BASE}/${QUERY_IDS.SearchTimeline}/SearchTimeline`;

    const body = JSON.stringify({
      variables,
      features,
      fieldToggles: TWEET_FIELD_TOGGLES,
      queryId: QUERY_IDS.SearchTimeline,
    });

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: this.getHeaders(),
        body,
      });

      if (!response.ok) {
        const text = await response.text();
        return {
          success: false,
          error: `HTTP ${response.status}: ${text.slice(0, 200)}`,
        };
      }

      const data = (await response.json()) as {
        data?: {
          search_by_raw_query?: {
            search_timeline?: {
              timeline?: {
                instructions?: Array<{
                  entries?: Array<{
                    content?: {
                      itemContent?: {
                        tweet_results?: {
                          result?: GraphqlTweetResult;
                        };
                      };
                    };
                  }>;
                }>;
              };
            };
          };
        };
        errors?: Array<{ message: string }>;
      };

      if (data.errors && data.errors.length > 0) {
        return {
          success: false,
          error: data.errors.map((e) => e.message).join(', '),
        };
      }

      const instructions = data.data?.search_by_raw_query?.search_timeline?.timeline?.instructions;
      const tweets = this.parseTweetsFromInstructions(instructions);

      return {
        success: true,
        tweets,
      };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  /**
   * Fetch the account associated with the current cookies
   */
  async getCurrentUser(): Promise<CurrentUserResult> {
    const candidateUrls = [
      'https://x.com/i/api/account/settings.json',
      'https://api.twitter.com/1.1/account/settings.json',
      'https://x.com/i/api/account/verify_credentials.json?skip_status=true&include_entities=false',
      'https://api.twitter.com/1.1/account/verify_credentials.json?skip_status=true&include_entities=false',
    ];

    let lastError: string | undefined;

    for (const url of candidateUrls) {
      try {
        const response = await fetch(url, {
          method: 'GET',
          headers: this.getHeaders(),
        });

        if (!response.ok) {
          const text = await response.text();
          lastError = `HTTP ${response.status}: ${text.slice(0, 200)}`;
          continue;
        }

        // biome-ignore lint/suspicious/noExplicitAny: Twitter API response is dynamic here
        let data: any;
        try {
          data = await response.json();
        } catch (error) {
          lastError = error instanceof Error ? error.message : String(error);
          continue;
        }

        const username =
          typeof data?.screen_name === 'string'
            ? data.screen_name
            : typeof data?.user?.screen_name === 'string'
              ? data.user.screen_name
              : null;

        const name =
          typeof data?.name === 'string'
            ? data.name
            : typeof data?.user?.name === 'string'
              ? data.user.name
              : (username ?? '');

        const userId =
          typeof data?.user_id === 'string'
            ? data.user_id
            : typeof data?.user_id_str === 'string'
              ? data.user_id_str
              : typeof data?.user?.id_str === 'string'
                ? data.user.id_str
                : typeof data?.user?.id === 'string'
                  ? data.user.id
                  : null;

        if (username && userId) {
          return {
            success: true,
            user: {
              id: userId,
              username,
              name: name || username,
            },
          };
        }

        lastError = 'Could not determine current user from response';
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }
    }

    // Fallback: scrape the authenticated settings page (HTML) for screen_name/user_id
    const profilePages = ['https://x.com/settings/account', 'https://twitter.com/settings/account'];
    for (const page of profilePages) {
      try {
        const response = await fetch(page, {
          headers: {
            cookie: `auth_token=${this.authToken}; ct0=${this.ct0}`,
            'user-agent': this.userAgent,
          },
        });

        if (!response.ok) {
          lastError = `HTTP ${response.status} (settings page)`;
          continue;
        }

        const html = await response.text();
        const usernameMatch = html.match(/"screen_name":"([^"]+)"/);
        const idMatch = html.match(/"user_id"\s*:\s*"(\d+)"/);
        const nameMatch = html.match(/"name":"([^"\\]*(?:\\.[^"\\]*)*)"/);

        const username = usernameMatch?.[1];
        const userId = idMatch?.[1];
        const name = nameMatch?.[1]?.replace(/\\"/g, '"');

        if (username && userId) {
          return {
            success: true,
            user: {
              id: userId,
              username,
              name: name || username,
            },
          };
        }

        lastError = 'Could not parse settings page for user info';
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }
    }

    return {
      success: false,
      error: lastError ?? 'Unknown error fetching current user',
    };
  }

  /**
   * Get replies to a tweet by ID
   */
  async getReplies(tweetId: string): Promise<SearchResult> {
    const response = await this.fetchTweetDetail(tweetId);
    if (!response.success) return response;

    const instructions = response.data.threaded_conversation_with_injections_v2?.instructions;
    const tweets = this.parseTweetsFromInstructions(instructions);
    const replies = tweets.filter((tweet) => tweet.inReplyToStatusId === tweetId);

    return { success: true, tweets: replies };
  }

  /**
   * Get full conversation thread for a tweet ID
   */
  async getThread(tweetId: string): Promise<SearchResult> {
    const response = await this.fetchTweetDetail(tweetId);
    if (!response.success) return response;

    const instructions = response.data.threaded_conversation_with_injections_v2?.instructions;
    const tweets = this.parseTweetsFromInstructions(instructions);

    const target = tweets.find((t) => t.id === tweetId);
    const rootId = target?.conversationId || tweetId;
    const thread = tweets.filter((tweet) => tweet.conversationId === rootId);

    thread.sort((a, b) => {
      const aTime = a.createdAt ? Date.parse(a.createdAt) : 0;
      const bTime = b.createdAt ? Date.parse(b.createdAt) : 0;
      return aTime - bTime;
    });

    return { success: true, tweets: thread };
  }
}
