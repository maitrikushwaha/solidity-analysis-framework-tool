pragma solidity ^0.4.25;

contract OysterPearl {
    uint256 public claimAmount;
    mapping (address => uint256) public balanceOf;

    function claim() public {
        require(block.timestamp >= 60);
        balanceOf[msg.sender] -= claimAmount;
    }
}