pragma solidity ^0.4.25;

contract BITVesting {
    uint256 public releaseDate;

    function claim () external returns (bool success) {
        require(block.timestamp > releaseDate);
        selfdestruct(msg.sender);
        return true;
    }
}