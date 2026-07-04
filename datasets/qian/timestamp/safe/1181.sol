pragma solidity ^0.4.25;

contract AqwireToken {
    uint256 public unlockTime;

    function transfer() public returns (bool) {
        require(block.timestamp >= unlockTime);
        return true;
    }
}