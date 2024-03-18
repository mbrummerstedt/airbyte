#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

from abc import ABC
from http import HTTPStatus
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional
import json

from requests import Response
from airbyte_protocol.models import SyncMode
from source_amazon_ads.schemas import (
    Keywords,
    NegativeKeywords,
    CampaignNegativeKeywords,
    ProductAd,
    ProductAdGroupBidRecommendations,
    ProductAdGroups,
    ProductAdGroupSuggestedKeywords,
    ProductCampaign,
    ProductTargeting,
)
from source_amazon_ads.streams.common import AmazonAdsStream, SubProfilesStream
from airbyte_cdk.sources.streams.http import HttpSubStream

class SponsoredProductsV3(SubProfilesStream):
    """
    This Stream supports the Sponsored Products v3 API, which requires POST methods
    https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_filter = kwargs.get("config", {}).get("state_filter")

    @property
    def http_method(self, **kwargs) -> str:
        return "POST"

    def request_headers(self, profile_id: str = None, *args, **kwargs) -> MutableMapping[str, Any]:
        headers = super().request_headers(*args, **kwargs)
        headers["Accept"] = self.content_type
        headers["Content-Type"] = self.content_type
        return headers

    def next_page_token(self, response: Response) -> str:
        if not response:
            return None
        return response.json().get("nextToken", None)

    def request_body_json(self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None) -> Mapping[str, Any]:
        request_body = {}
        if self.state_filter:
            request_body["stateFilter"] = {
                "include": self.state_filter
            }
        request_body["maxResults"] = self.page_size
        request_body["nextToken"] = next_page_token
        return request_body

class SponsoredProductCampaigns(SponsoredProductsV3):
    """
    This stream corresponds to Amazon Ads API - Sponsored Products (v3) Campaigns
    https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod#tag/Campaigns/operation/ListSponsoredProductsCampaigns
    """

    primary_key = "campaignId"
    data_field = "campaigns"
    state_filter = None
    model = ProductCampaign
    content_type = "application/vnd.spCampaign.v3+json"

    def path(self, **kwargs) -> str:
        return "sp/campaigns/list"

class SponsoredProductAdGroups(SponsoredProductsV3):
    """
    This stream corresponds to Amazon Ads API - Sponsored Products (v3) Ad groups
    https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod#tag/Ad-groups/operation/ListSponsoredProductsAdGroups
    """

    primary_key = "adGroupId"
    data_field = "adGroups"
    content_type = "application/vnd.spAdGroup.v3+json"
    model = ProductAdGroups

    def path(self, **kwargs) -> str:
        return "/sp/adGroups/list"

class SponsoredProductAdGroupWithSlicesABC(SponsoredProductsV3, ABC):
    """ABC Class for extraction of additional information for each known sp ad group"""

    primary_key = "adGroupId"

    def __init__(self, *args, **kwargs):
        self.__args = args
        self.__kwargs = kwargs
        super().__init__(*args, **kwargs)

    def stream_slices(
        self, *, sync_mode: SyncMode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        yield from SponsoredProductAdGroups(*self.__args, **self.__kwargs).read_records(
            sync_mode=sync_mode, cursor_field=cursor_field, stream_slice=None, stream_state=stream_state
        )

    def parse_response(self, response: Response, **kwargs) -> Iterable[Mapping]:

        resp = response.json()
        if response.status_code == HTTPStatus.OK:
            yield resp

        if response.status_code == HTTPStatus.BAD_REQUEST:
            # 400 error message for bids recommendation:
            #   Bid recommendation for AD group in Manual Targeted Campaign is not supported.
            # 400 error message for keywords recommendation:
            #   Getting keyword recommendations for AD Group in Auto Targeted Campaign is not supported
            self.logger.warning(
                f"Skip current AdGroup because it does not support request {response.request.url} for "
                f"{response.request.headers['Amazon-Advertising-API-Scope']} profile: {response.text}"
            )
        elif response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
            # 422 error message for bids recommendation:
            # No recommendations can be provided as the input ad group does not have any asins.
            self.logger.warning(
                f"Skip current AdGroup because the ad group {json.loads(response.request.body)['adGroupId']} does not have any asins {response.request.url}"
            )
        elif response.status_code == HTTPStatus.NOT_FOUND:
            # 404 Either the specified ad group identifier was not found,
            # or the specified ad group was found but no associated bid was found.
            self.logger.warning(
                f"Skip current AdGroup because the specified ad group has no associated bid {response.request.url} for "
                f"{response.request.headers['Amazon-Advertising-API-Scope']} profile: {response.text}"
            )

        else:
            response.raise_for_status()

class SponsoredProductAdGroupBidRecommendations(SponsoredProductAdGroupWithSlicesABC):
    """
    This stream corresponds to Amazon Ads API - Sponsored Products (v3) Ad group bid recommendations, now referred to as "Target Bid Recommendations" by Amazon Ads
    https://advertising.amazon.com/API/docs/en-us/sponsored-display/3-0/openapi#tag/Bid-Recommendations/operation/getTargetBidRecommendations
    """
    primary_key = None
    data_field = "bidRecommendations"
    content_type = "application/vnd.spthemebasedbidrecommendation.v4+json"
    model = ProductAdGroupBidRecommendations

    def path(self, stream_slice: Mapping[str, Any] = None, **kwargs) -> str:
        return "/sp/targets/bid/recommendations"

    def request_body_json(self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None) -> Mapping[str, Any]:
        request_body = {}
        request_body["targetingExpressions"] = [{
            "type": "KEYWORD_BROAD_MATCH",
            "value": "hello"
        }]
        request_body["adGroupId"] = stream_slice["adGroupId"]
        request_body["campaignId"] = stream_slice["campaignId"]
        request_body["recommendationType"] = "BIDS_FOR_EXISTING_AD_GROUP"
        return request_body



class SponsoredProductAdGroupSuggestedKeywords(SponsoredProductAdGroupWithSlicesABC):
    """Docs:
    Latest API:
        https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod#/Keyword%20Targets/getRankedKeywordRecommendation
        POST /sp/targets/keywords/recommendations
        Note: does not work, always get "403 Forbidden"

    V2 API:
        https://advertising.amazon.com/API/docs/en-us/sponsored-products/2-0/openapi#/Suggested%20keywords
        GET /v2/sp/adGroups/{{adGroupId}}>/suggested/keywords
    """

    model = ProductAdGroupSuggestedKeywords

    def path(self, stream_slice: Mapping[str, Any] = None, **kwargs) -> str:
        return f"v2/sp/adGroups/{stream_slice['adGroupId']}/suggested/keywords"


class SponsoredProductKeywords(SponsoredProductsV3):
    """
    This stream corresponds to Amazon Ads Sponsored Products v3 API - Sponsored Products Keywords
    https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod#tag/Keywords/operation/ListSponsoredProductsKeywords
    """

    primary_key = "keywordId"
    data_field = "keywords"
    content_type = "application/vnd.spKeyword.v3+json"
    model = Keywords

    def path(self, **kwargs) -> str:
        return "sp/keywords/list"


class SponsoredProductNegativeKeywords(SponsoredProductsV3):
    """
    This stream corresponds to Amazon Ads Sponsored Products v3 API - Sponsored Products Negative Keywords
    https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod#tag/Negative-keywords/operation/ListSponsoredProductsNegativeKeywords
    """

    primary_key = "keywordId"
    data_field = "negativeKeywords"
    content_type = "application/vnd.spNegativeKeyword.v3+json"
    model = NegativeKeywords

    def path(self, **kwargs) -> str:
        return "sp/negativeKeywords/list"


class SponsoredProductCampaignNegativeKeywords(SponsoredProductsV3):
    """
    This stream corresponds to Amazon Ads Sponsored Products v3 API - Sponsored Products Negative Keywords
    https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod#tag/Campaign-negative-keywords/operation/ListSponsoredProductsCampaignNegativeKeywords
    """

    primary_key = "keywordId"
    data_field = "campaignNegativeKeywords"
    content_type = "application/vnd.spCampaignNegativeKeyword.v3+json"
    model = CampaignNegativeKeywords

    def path(self, **kwargs) -> str:
        return "sp/campaignNegativeKeywords/list"


class SponsoredProductAds(SponsoredProductsV3):
    """
    This stream corresponds to Amazon Ads v3 API - Sponsored Products Ads
    https://advertising.amazon.com/API/docs/en-us/sponsored-products/3-0/openapi/prod#tag/Product-ads/operation/ListSponsoredProductsProductAds
    """

    primary_key = "adId"
    data_field = "productAds"
    content_type = "application/vnd.spProductAd.v3+json"
    model = ProductAd

    def path(self, **kwargs) -> str:
        return "sp/productAds/list"


class SponsoredProductTargetings(SponsoredProductsV3):
    """
    This stream corresponds to Amazon Ads Sponsored Products v3 API - Sponsored Products Targeting Clauses
    """

    primary_key = "targetId"
    data_field = "targetingClauses"
    content_type = "application/vnd.spTargetingClause.v3+json"
    model = ProductTargeting

    def path(self, **kwargs) -> str:
        return "sp/targets/list"
