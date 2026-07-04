pragma solidity ^0.4.25;

contract TransactionManager{

    function addToWhitelist(address _wallet, address _target) returns (uint256){
        uint256 whitelistPeriod = 10;
        uint256 whitelistAfter = block.timestamp + whitelistPeriod;
        return whitelistAfter;
    }
}