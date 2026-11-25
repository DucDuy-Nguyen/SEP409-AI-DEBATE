using System;
using System.Collections.Generic;

namespace SystemService.BLL.Common.Payment
{
    /// <summary>
    /// Centralized credit rule codes, default pricing, and competition scale mapping.
    /// </summary>
    public static class CreditRuleCodes
    {
        public const string AiPracticeMatch = "AI_PRACTICE_MATCH";
        public const string AiPracticeNoRag = "AI_PRACTICE_NO_RAG";
        public const string AiHint = "AI_HINT";

        public const string CompetitionSmall = "COMPETITION_SMALL";
        public const string CompetitionMedium = "COMPETITION_MEDIUM";
        public const string CompetitionLarge = "COMPETITION_LARGE";

        public const string DailyLogin = "DAILY_LOGIN";
        public const string FirstLogin = "FIRST_LOGIN";

        // Legacy rule disabled from all fee deduction logic.
        public const string P2pMatchPerUser = "P2P_MATCH_PER_USER";

        public const string ScaleSmall = "SMALL";
        public const string ScaleMedium = "MEDIUM";
        public const string ScaleLarge = "LARGE";

        public const int MaxIndividualSmall = 8;
        public const int MaxIndividualMedium = 16;
        public const int MaxIndividualLarge = 32;

        public const int MaxTeamsSmall = 4;
        public const int MaxTeamsMedium = 8;
        public const int MaxTeamsLarge = 16;

        public static readonly IReadOnlyDictionary<string, long> DefaultRulePrices =
            new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase)
            {
                [AiPracticeMatch] = 150,
                [AiPracticeNoRag] = 110,
                [AiHint] = 5,
                [CompetitionSmall] = 500,
                [CompetitionMedium] = 1200,
                [CompetitionLarge] = 2500,
                [DailyLogin] = 20,
                [FirstLogin] = 200,
                [P2pMatchPerUser] = 0
            };

        public static long GetDefaultPrice(string ruleCode)
        {
            return DefaultRulePrices.TryGetValue(ruleCode, out var amount) ? amount : 0;
        }

        public static bool TryResolveCompetitionScale(
            string? competitionType,
            int? maxParticipants,
            int? maxTeams,
            out string scale,
            out string ruleCode,
            out int normalizedMaxParticipants,
            out int? normalizedMaxTeams,
            out string? errorMessage)
        {
            scale = string.Empty;
            ruleCode = string.Empty;
            normalizedMaxParticipants = 0;
            normalizedMaxTeams = null;
            errorMessage = null;

            var normalizedType = competitionType?.Trim().ToUpperInvariant();
            bool isIndividual = normalizedType is "INDIVIDUAL" or "1V1";
            bool isTeam = normalizedType is "TEAM" or "2V2";

            if (!isIndividual && !isTeam)
            {
                errorMessage = "CompetitionType must be either INDIVIDUAL (1v1) or TEAM (2v2).";
                return false;
            }

            if (isIndividual)
            {
                int capacity = maxParticipants ?? 0;
                if (capacity <= 0)
                {
                    errorMessage = "MaxParticipants is required and must be greater than 0 for INDIVIDUAL competitions.";
                    return false;
                }

                if (capacity > MaxIndividualLarge)
                {
                    errorMessage = $"Maximum capacity for INDIVIDUAL competitions is {MaxIndividualLarge} participants (LARGE).";
                    return false;
                }

                normalizedMaxParticipants = capacity;
                if (capacity <= MaxIndividualSmall)
                {
                    scale = ScaleSmall;
                    ruleCode = CompetitionSmall;
                }
                else if (capacity <= MaxIndividualMedium)
                {
                    scale = ScaleMedium;
                    ruleCode = CompetitionMedium;
                }
                else
                {
                    scale = ScaleLarge;
                    ruleCode = CompetitionLarge;
                }

                return true;
            }

            // TEAM (2v2): each team consists of 2 participants.
            int teams;
            if (maxTeams.HasValue && maxTeams.Value > 0)
            {
                if (maxParticipants.HasValue && maxParticipants.Value != maxTeams.Value * 2)
                {
                    errorMessage = "MaxParticipants must equal MaxTeams * 2 for TEAM competitions.";
                    return false;
                }

                teams = maxTeams.Value;
                normalizedMaxParticipants = teams * 2;
            }
            else if (maxParticipants.HasValue)
            {
                if (maxParticipants.Value <= 0)
                {
                    errorMessage = "MaxParticipants must be greater than 0 for TEAM competitions.";
                    return false;
                }

                if (maxParticipants.Value % 2 != 0)
                {
                    errorMessage = "TEAM MaxParticipants must be even (2 participants per team).";
                    return false;
                }

                teams = maxParticipants.Value / 2;
                normalizedMaxParticipants = maxParticipants.Value;
            }
            else
            {
                errorMessage = "MaxParticipants (or MaxTeams) is required and must be greater than 0 for TEAM competitions.";
                return false;
            }

            if (teams > MaxTeamsLarge)
            {
                errorMessage = $"Maximum capacity for TEAM competitions is {MaxTeamsLarge} teams ({MaxIndividualLarge} participants, LARGE).";
                return false;
            }

            normalizedMaxTeams = teams;
            if (teams <= MaxTeamsSmall)
            {
                scale = ScaleSmall;
                ruleCode = CompetitionSmall;
            }
            else if (teams <= MaxTeamsMedium)
            {
                scale = ScaleMedium;
                ruleCode = CompetitionMedium;
            }
            else
            {
                scale = ScaleLarge;
                ruleCode = CompetitionLarge;
            }

            return true;
        }
    }
}
