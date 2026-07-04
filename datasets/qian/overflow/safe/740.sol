pragma solidity ^0.4.25;

contract Crowdsale {
    uint256 constant public STARTDATE = 1533686401;

    function buyTokens() public payable returns (bool success) {
        assert(block.timestamp >= STARTDATE);
        return true;
    }
}