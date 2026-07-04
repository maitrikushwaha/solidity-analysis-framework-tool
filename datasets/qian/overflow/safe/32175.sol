pragma solidity ^0.4.25;

contract StupidCrowdsale {

    uint256 constant public START = 1514764800;

    function getRate() public returns (uint16) {
        if (block.timestamp < START)
            return 1000;
        return 500;
    }
}