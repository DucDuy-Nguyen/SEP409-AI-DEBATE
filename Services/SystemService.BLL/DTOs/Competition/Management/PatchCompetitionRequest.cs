using System;
using System.Text.Json.Serialization;

namespace SystemService.BLL.DTOs.Competition.Management
{
    public class PatchCompetitionRequest
    {
        private string? _title;
        private string? _description;
        private int? _formatId;
        private int? _maxParticipants;
        private DateTime? _registrationStart;
        private DateTime? _registrationEnd;
        private DateTime? _startDate;
        private DateTime? _endDate;
        private bool? _isPublic;

        public string? Title
        {
            get => _title;
            set
            {
                _title = value;
                HasTitle = true;
            }
        }

        public string? Description
        {
            get => _description;
            set
            {
                _description = value;
                HasDescription = true;
            }
        }

        public int? FormatId
        {
            get => _formatId;
            set
            {
                _formatId = value;
                HasFormatId = true;
            }
        }

        public int? MaxParticipants
        {
            get => _maxParticipants;
            set
            {
                _maxParticipants = value;
                HasMaxParticipants = true;
            }
        }

        public DateTime? RegistrationStart
        {
            get => _registrationStart;
            set
            {
                _registrationStart = value;
                HasRegistrationStart = true;
            }
        }

        public DateTime? RegistrationEnd
        {
            get => _registrationEnd;
            set
            {
                _registrationEnd = value;
                HasRegistrationEnd = true;
            }
        }

        public DateTime? StartDate
        {
            get => _startDate;
            set
            {
                _startDate = value;
                HasStartDate = true;
            }
        }

        public DateTime? EndDate
        {
            get => _endDate;
            set
            {
                _endDate = value;
                HasEndDate = true;
            }
        }

        public bool? IsPublic
        {
            get => _isPublic;
            set
            {
                _isPublic = value;
                HasIsPublic = true;
            }
        }

        [JsonIgnore]
        public bool HasTitle { get; private set; }

        [JsonIgnore]
        public bool HasDescription { get; private set; }

        [JsonIgnore]
        public bool HasFormatId { get; private set; }

        [JsonIgnore]
        public bool HasMaxParticipants { get; private set; }

        [JsonIgnore]
        public bool HasRegistrationStart { get; private set; }

        [JsonIgnore]
        public bool HasRegistrationEnd { get; private set; }

        [JsonIgnore]
        public bool HasStartDate { get; private set; }

        [JsonIgnore]
        public bool HasEndDate { get; private set; }

        [JsonIgnore]
        public bool HasIsPublic { get; private set; }

        [JsonIgnore]
        public bool HasAnyProperty => HasTitle || HasDescription || HasFormatId || HasMaxParticipants ||
                                      HasRegistrationStart || HasRegistrationEnd || HasStartDate ||
                                      HasEndDate || HasIsPublic;
    }
}
