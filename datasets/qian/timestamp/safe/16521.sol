pragma solidity ^0.4.25;

contract SponsoredItemGooRaffle {
    uint256 private raffleEndTime;

    function drawRandomWinner() public {
        require(raffleEndTime < block.timestamp);
        return;
    }
}