pragma solidity ^0.4.25;

contract TimedCrowdsale {
    uint openingTime = 0;

    function TimedCrowdsal(uint256 _openingTime) public returns (bool) {
        require(_openingTime >= block.timestamp);
        openingTime = _openingTime;
        return true;
    }
}