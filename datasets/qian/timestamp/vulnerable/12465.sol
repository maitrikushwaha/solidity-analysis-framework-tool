pragma solidity ^0.4.25;

contract ShareXTokenVault {
    mapping(address => uint256) public timeLocks;
    mapping(address => uint256) public claimed;

    function canCollect() public view returns(bool) {
        return block.timestamp > timeLocks[msg.sender] && claimed[msg.sender] == 0;
    }
}