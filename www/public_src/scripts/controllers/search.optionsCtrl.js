angular.module('aiddataDET')
.controller('OptionsCtrl', function($scope, $rootScope, $log) {
  $scope.dataset = {};

  $scope.options = [
    {
      name: "Extract Options",
      type: "checkbox",
      loc: "options.extract_types",
      data: []
    },
    {
      name: "Resources",
      type: "checkbox",
      loc: "resources",
      data: []
    },
    {
      name: "Metadata",
      type: "paragraph"
    }
  ];

  $scope.toggleOption = function (isChecked, option) {
    $log.debug(isChecked, option);
  };

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;
    $log.debug(data);

    if (data.type !== 'raster') { return; }
    _.each($scope.options, function(option) {
      if (option.loc) {
        option.data = _.chain($scope.dataset)
          .get(option.loc)
          .map(function(choice) {
            return _.isString(choice) ? { name: choice } : choice;
          })
          .value();
      }
    });

    console.log($scope.options);
  });

  $scope.getTimeStamp = function (date, format) {
    var timeFormatter = d3.timeFormat("%b %d, %Y");
    var timeParser = d3.timeParse(format),
        formDate = timeFormatter(timeParser(date));
    $log.debug(formDate);
    return formDate;
  };

});
