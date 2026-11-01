using System;
using System.Linq;
using SystemService.BLL.Services.Competition.Implementations;
using Xunit;

public sealed class CompetitionBracketLayoutTests
{
    [Theory]
    [InlineData(2)]
    [InlineData(4)]
    [InlineData(8)]
    [InlineData(16)]
    public void SeedSlots_form_unique_balanced_first_round_pairs(int size)
    {
        var slots = CompetitionTournamentService.SeedSlots(size);
        Assert.Equal(size, slots.Count);
        Assert.Equal(Enumerable.Range(1, size), slots.OrderBy(x => x));
        for (var i = 0; i < size; i += 2)
            Assert.Equal(size + 1, slots[i] + slots[i + 1]);
    }

    [Fact]
    public void Five_entrants_have_three_first_round_byes()
    {
        var slots = CompetitionTournamentService.SeedSlots(8);
        Assert.Equal(3, Enumerable.Range(0, 4).Count(match =>
            (slots[match * 2] <= 5) != (slots[match * 2 + 1] <= 5)));
    }
}
