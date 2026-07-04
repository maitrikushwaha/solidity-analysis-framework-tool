// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;                                    
contract Reentrancy_bonus {

    mapping(address => uint) private rewardsForA;
    
    function depositReward(address _beneficiary) public payable {
        require(msg.value > 0, "Must send ETH to deposit rewards");
        rewardsForA[_beneficiary] += msg.value;
    }

    function withdrawReward() public {                     
        uint amountToWithdraw = rewardsForA[msg.sender];
        require(amountToWithdraw > 0, "No rewards available to withdraw");
        rewardsForA[msg.sender] = 0;                       
        (bool success, ) = msg.sender.call{value:          
            amountToWithdraw}("");
        require(success, "Transfer failed");

    }
}

