function makeDialog (type, configs) {
  return {
    clickOutsideToClose: configs.clickOutsideToClose ? configs.clickOutsideToClose : true,

    templateUrl: 'views/components/modalTemplate.html',

    controller: function DialogController($scope, $sce, $mdDialog) {
      $scope.configs = configs;
      $scope.type = type;
      if (configs.content || configs.textContent) {
        var content = configs.content ? configs.content :
          '<p>' + configs.textContent + '</p>';
        $scope.trustedContent = $sce.trustAsHtml(content);
      }

      $scope.cancelDialog = function() {
        $mdDialog.cancel();
      };
      $scope.closeDialog = function() {
        $mdDialog.hide();
      };
    }
  };
}
angular.module('aiddataDET')
  .factory('modalFactory', function($log, $mdDialog) {
    return {
      dialog: function (configs) {
        return makeDialog('dialog', configs);
      },
      confirm: function (configs) {
        return makeDialog('confirm', configs);
      },
      alert: function (configs) {
        return makeDialog('alert', {
          title: configs.message,
          name: configs.name
        });
      }
    };
  });
